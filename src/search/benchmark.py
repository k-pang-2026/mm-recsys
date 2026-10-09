"""Serial, real localhost HTTP benchmark including encoding and request validation."""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
from pathlib import Path
import threading
from time import perf_counter, sleep
import httpx
import numpy as np
import uvicorn

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.search.api import create_app
from src.search.queries import freeze_queries


def percentiles(values: list[float]) -> dict:
    return dict(zip(('p50_ms', 'p95_ms', 'p99_ms'), [float(v) for v in np.percentile(values, [50, 95, 99])]))


def benchmark(cfg: dict) -> dict:
    folder = freeze_queries(cfg); queries = json.loads((folder/'valid.json').read_text())
    app = create_app(cfg)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='error', loop='asyncio', lifespan='on'))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    started = perf_counter()
    try:
        while not server.started:
            if not thread.is_alive() or perf_counter()-started > 90:
                raise RuntimeError('real HTTP server did not become ready')
            sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        results = {}; smoke = []; all_http = []; all_core = []
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
            health = client.get('/health'); assert health.status_code == 200 and health.json()['search_ready']
            for mode in ('text', 'image', 'hybrid'):
                active = [q for q in queries if q['mode'] == mode]
                payloads = []
                for query in active:
                    payload = {'top_k': 10}
                    if query['query_text']:
                        payload['query_text'] = query['query_text']
                    if query['query_image_path']:
                        payload['query_image'] = base64.b64encode((folder/query['query_image_path']).read_bytes()).decode()
                    payloads.append(payload)
                observed = []; core = []
                for i in range(cfg['benchmark']['warmup']+cfg['benchmark']['requests']):
                    start = perf_counter(); response = client.post('/api/search', json=payloads[i%len(payloads)])
                    elapsed = (perf_counter()-start)*1000
                    if response.status_code != 200:
                        raise ValueError(f'{mode} HTTP search failed: {response.status_code}: {response.text}')
                    body = response.json()
                    if set(body) != {'search_type', 'results', 'latency_ms', 'total_count'} or body['search_type'] != mode:
                        raise ValueError('search API response contract mismatch')
                    if i >= cfg['benchmark']['warmup']:
                        observed.append(elapsed); core.append(float(body['latency_ms']))
                results[mode] = {'requests': len(observed), 'warmup': cfg['benchmark']['warmup'],
                                  'http': percentiles(observed), 'service': percentiles(core),
                                  'http_samples_ms': observed, 'service_samples_ms': core}
                smoke.append({'mode': mode, 'status_code': 200}); all_http.extend(observed); all_core.extend(core)
            for payload in ({}, {'query_text': 'shirt', 'top_k': 0}, {'query_image': 'invalid'},
                            {'query_text': 'shirt', 'top_k': True}):
                response = client.post('/api/search', json=payload)
                if response.status_code != 422:
                    raise ValueError('invalid search payload must return 422')
                smoke.append({'invalid_payload': payload, 'status_code': 422})
            image_query = next(q for q in queries if q['mode'] == 'image')
            data = (folder/image_query['query_image_path']).read_bytes()
            response = client.post('/api/search', files={'query_image': ('query.png', data, 'image/png')},
                                   data={'query_text': 'shirt', 'top_k': '10'})
            if response.status_code != 200 or response.json()['search_type'] != 'hybrid':
                raise ValueError('multipart hybrid search failed')
            smoke.append({'mode': 'multipart_hybrid', 'status_code': 200})
        bundle = app.app.state.search.searcher.bundle['manifest']
        return {'scale': cfg['scale'], 'status': 'MEASURED', 'concurrency': 1, 'transport': 'real localhost HTTP, persistent connection',
                'data_fingerprint': bundle['identity']['data_fingerprint'], 'model_fingerprint': bundle['fingerprint'],
                'input_queries': 'frozen valid queries; no test labels used', 'query_manifest_sha256': file_hash(folder/'manifest.json'),
                'config_fingerprint': fingerprint(cfg), 'per_mode': results, 'aggregate_http': percentiles(all_http),
                'aggregate_service': percentiles(all_core), 'smoke': smoke, 'target_p95_ms': cfg['targets']['search_p95_ms'],
                'target_pass': all(r['http']['p95_ms'] <= cfg['targets']['search_p95_ms'] for r in results.values()),
                'environment': {'platform': platform.platform(), 'python': platform.python_version(), 'cpu_logical': os.cpu_count(),
                                'device': cfg['search']['device'], 'torch_threads': cfg['search']['torch_threads'],
                                'faiss_threads': cfg['search']['faiss']['threads']},
                'timing_scope': 'HTTP roundtrip includes request serialization/validation, image decoding, CLIP, ANN and postprocessing; model startup excluded',
                'final_four_service_docker_reproduction': 'UNMEASURED'}
    finally:
        server.should_exit = True; thread.join(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--require-target', action='store_true')
    args = parser.parse_args()
    cfg = load_config(); result = benchmark(cfg)
    write_json(args.output or Path(f'docs/results/search_latency_{cfg["scale"]}.json'), result)
    print(json.dumps({'scale': result['scale'], 'aggregate_http': result['aggregate_http'],
                      'per_mode': {m: r['http'] for m, r in result['per_mode'].items()}, 'target_pass': result['target_pass']}, indent=2))
    if args.require_target and not result['target_pass']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
