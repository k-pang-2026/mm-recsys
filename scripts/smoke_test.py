"""Check the deployed API, multipart, sessions and dashboard; optionally benchmark."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import platform
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.schemas import RecommendResponse, SearchResponse
from docker.http import request, wait_ready
from docker.runtime import runtime_config


def multipart(url: str, text: str, image: bytes) -> dict:
    boundary = 'mm-recsys-' + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="query_text"\r\n\r\n{text}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="query_image"; filename="query.png"\r\n'
            'Content-Type: image/png\r\n\r\n').encode() + image + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(url + '/api/search', data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30) as response:
        return json.load(response)


def quantiles(values: list[float]) -> dict:
    import numpy as np
    if not values or not np.isfinite(values).all():
        raise ValueError('finite nonempty samples required')
    stats = np.asarray(np.percentile(values, [50, 95, 99]))
    return {name: float(stats[i]) for i, name in enumerate(('p50_ms', 'p95_ms', 'p99_ms'))}


def run(cfg: dict, api: str, dashboard: str, benchmark: bool) -> dict:
    import pandas as pd
    from src.search.queries import freeze_queries
    wait_ready(api, float(os.getenv('READY_TIMEOUT_SECONDS', '21600')))
    health = request(api + '/health')
    if not health.get('search_ready') or not health.get('recommend_ready') or health.get('scale') != cfg['scale']:
        raise ValueError('both compatible services must be ready at the requested scale')
    if health.get('model_version') != 'v1.0':
        raise ValueError('fixed B10 benchmark targets the initial v1.0 bundle; measure promoted releases separately')
    folder = freeze_queries(cfg)
    queries = json.loads((folder / 'valid.json').read_text())
    payloads: dict[str, list[dict]] = {mode: [] for mode in ('text', 'image', 'hybrid')}
    for q in queries:
        payload = dict(top_k=cfg['search']['top_k'])
        if q['query_text']:
            payload['query_text'] = q['query_text']
        if q['query_image_path']:
            payload['query_image'] = base64.b64encode((folder / q['query_image_path']).read_bytes()).decode()
        payloads[q['mode']].append(payload)
    responses = {}
    for mode, values in payloads.items():
        body = request(api + '/api/search', values[0])
        parsed = SearchResponse.model_validate(body)
        if parsed.search_type != mode or not parsed.results:
            raise ValueError(f'{mode} search must return typed nonempty results')
        responses[mode] = body
    hybrid = next(q for q in queries if q['mode'] == 'hybrid')
    body = multipart(api, hybrid['query_text'], (folder / hybrid['query_image_path']).read_bytes())
    if SearchResponse.model_validate(body).search_type != 'hybrid':
        raise ValueError('multipart must preserve hybrid mode')
    responses['multipart'] = body
    try:
        request(api + '/api/search', {})
    except urllib.error.HTTPError as error:
        if error.code != 422:
            raise
    else:
        raise ValueError('empty search must return 422')
    root = Path(cfg['paths']['data_dir'])
    users = sorted(pd.read_parquet(root / 'users.parquet').user_id.astype(str))
    for label, uid in [('known_user', users[0]), ('new_user', '__docker_new_' + uuid.uuid4().hex)]:
        body = request(api + '/api/recommend?user_id=' + uid + '&top_n=10')
        if not RecommendResponse.model_validate(body).recommendations:
            raise ValueError('known/new-user recommendation must return items')
        responses[label] = body
    uid = '__docker_session_' + uuid.uuid4().hex
    item = responses['text']['results'][0]['product_id']
    event = dict(event_id=uuid.uuid4().hex, user_id=uid, product_id=item,
                 event_type='view', session_id='docker-smoke', category='smoke')
    if not request(api + '/api/event', event)['applied']:
        raise ValueError('session event must be applied')
    request(api + '/api/feedback', event)
    body = request(api + '/api/recommend?user_id=' + uid + '&top_n=10')
    if item not in RecommendResponse.model_validate(body).session_context.recent_clicks:
        raise ValueError('session context did not reflect the live Redis event')
    responses['session'] = body
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in ('/', '/_stcore/health'):
        with opener.open(dashboard.rstrip('/') + path, timeout=10) as response:
            if response.status != 200:
                raise ValueError('dashboard must return HTTP 200')
    manifest = root / 'split_manifest.json'
    model = Path(cfg['paths']['model_dir'])
    model_paths = [model / 'v1.0' / name for name in ('meta.json', 'index_manifest.json', 'ranking/meta.json', 'session/meta.json')]
    search = model / cfg['search']['artifact_subdir']
    for kind in ('embeddings', 'indexes'):
        pointer = search / f'{kind}_current.json'
        model_paths.append(pointer)
        model_paths.append(search / kind / json.loads(pointer.read_text())['fingerprint'] / 'manifest.json')
    health_after = request(api + '/health')
    if health_after.get('model_version') != health['model_version']:
        raise ValueError('active model changed during smoke')
    report = dict(status='PASS', acceptance='UNMEASURED', scale=cfg['scale'],
        data_fingerprint=json.loads(manifest.read_text())['generation_fingerprint'],
        manifest_sha256=file_hash(manifest), config_fingerprint=fingerprint(cfg),
        models={str(p): file_hash(p) for p in model_paths},
        source_hashes={str(p): file_hash(p) for p in [Path(__file__), Path('docker/runtime.py'), Path('docker/http.py'), Path('docker/serve.py')]},
        health=health, responses=responses, checks=dict(api_schemas='PASS', multipart='PASS',
            invalid_search='PASS', session_response='PASS', dashboard_http='PASS'),
        scope='actual HTTP smoke; Streamlit HTTP health does not establish browser rendering')
    if benchmark:
        warmup, calls = cfg['benchmark']['warmup'], cfg['benchmark']['requests']
        if warmup < 10 or calls < 100 or cfg['benchmark']['concurrency'] != 1:
            raise ValueError('benchmark requires >=10 warmups and >=100 serial calls')
        modes = {}
        for mode in ('text', 'image', 'hybrid', 'recommendation'):
            http, native, pipelines = [], [], []
            for i in range(warmup + calls):
                started = time.perf_counter()
                result = (request(api + '/api/recommend?user_id=' + users[i % len(users)] + '&top_n=10')
                          if mode == 'recommendation' else request(api + '/api/search', payloads[mode][i % len(payloads[mode])]))
                elapsed = (time.perf_counter() - started) * 1000
                if mode == 'recommendation':
                    parsed_rec = RecommendResponse.model_validate(result)
                    stages = parsed_rec.pipeline_latency.model_dump()
                    core = stages['total_ms']
                else:
                    parsed_search = SearchResponse.model_validate(result)
                    if parsed_search.search_type != mode:
                        raise ValueError('search mode mismatch during benchmark')
                    core, stages = parsed_search.latency_ms, {}
                if i >= warmup:
                    http.append(elapsed); native.append(core); pipelines.append(stages)
            target = cfg['targets']['recommend_p95_ms' if mode == 'recommendation' else 'search_p95_ms']
            stats = quantiles(http)
            modes[mode] = dict(http=stats, service=quantiles(native), http_samples_ms=http,
                service_samples_ms=native, pipeline_samples=pipelines, warmup=warmup, requests=calls,
                concurrency=1, errors=0, target_p95_ms=target, status='PASS' if stats['p95_ms'] <= target else 'FAIL')
            print(f'Docker HTTP {mode}: p95={stats["p95_ms"]:.3f}ms', flush=True)
        from src.serving.feature_store import RedisFeatureStore, create_feature_store
        from src.evaluation.bench_latency import benchmark as feature_benchmark
        from src.recommendation.bench_candidate import benchmark as candidate_benchmark
        store = create_feature_store(cfg)
        if not isinstance(store, RedisFeatureStore):
            raise ValueError('Docker latency measurement requires the real Redis backend')
        try:
            feature = feature_benchmark(cfg, store)
        finally:
            store.close()
        candidate = candidate_benchmark(cfg, Path(cfg['paths']['model_dir']) / 'v1.0', 'valid')
        candidate['status'] = 'PASS' if candidate['candidate_count_min'] >= cfg['recommend']['candidate_k'] and candidate['p95_ms'] <= cfg['targets']['candidate_p95_ms'] else 'FAIL'
        in_docker = os.getenv('DOCKER_RUNTIME') == '1'
        candidate['environment']['docker_allocation'] = 'API container shared CPU/memory limits' if in_docker else 'native host'
        feature['environment']['docker'] = in_docker
        import importlib.metadata
        serving_runtime = Path(cfg['paths']['results_dir']) / 'serving_runtime.json'
        report['benchmark'] = dict(modes=modes, feature=feature, candidate=candidate,
            serving_runtime=json.loads(serving_runtime.read_text()),
            environment=dict(python=platform.python_version(), machine=platform.machine(), platform=platform.platform(),
                cpu_count=os.cpu_count(), gpu_used=False, docker=in_docker,
                packages={k: importlib.metadata.version(k) for k in ('torch','torchvision','transformers','faiss-cpu','redis')},
                cgroup={name: Path('/sys/fs/cgroup', name).read_text().strip()
                        for name in ('memory.max', 'cpu.max') if Path('/sys/fs/cgroup', name).is_file()}),
            settings=dict(faiss=cfg['search']['faiss'], fusion=cfg['search']['query_fusion'],
                batch_size=cfg['search']['batch_size'], cache='no response cache; resident models/indexes; generated queries',
                onnx=False, transport='actual HTTP, new connection per call', context_split='valid'))
        report['latency_status'] = 'PASS' if all(v['status'] == 'PASS' for v in modes.values()) and feature['status'] == candidate['status'] == 'PASS' else 'FAIL'
        report['benchmark']['health_after'] = request(api + '/health')
        if report['benchmark']['health_after'].get('model_version') != health['model_version']:
            raise ValueError('active model changed during fixed benchmark')
        if report['latency_status'] == 'FAIL':
            report['status'] = 'FAIL'
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default=os.getenv('API_URL', 'http://localhost:8000'))
    parser.add_argument('--dashboard-url', default='http://dashboard:8501')
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(); cfg = runtime_config()
    result = run(cfg, args.api_url.rstrip('/'), args.dashboard_url, args.benchmark)
    output = args.output or Path(f"docs/results/docker/smoke_{cfg['scale']}.json")
    preparation = Path(cfg['paths']['results_dir']) / 'preparation.json'
    write_json(Path(f"docs/results/docker/preparation_{cfg['scale']}.json"), json.loads(preparation.read_text()))
    write_json(output, result)
    if args.benchmark:
        write_json(Path('docs/results/latency.json'), result)
    print(f"Docker smoke: {result['status']} -> {output}")
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
