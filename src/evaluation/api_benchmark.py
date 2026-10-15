"""Real localhost HTTP over the shared API and Redis, separate from vector timing."""
from __future__ import annotations

import base64
import copy
import json
import threading
import time
import uuid
from pathlib import Path

import httpx
import numpy as np
import uvicorn

from src.common.artifacts import fingerprint
from src.common.schemas import RecommendResponse, SearchResponse
from src.serving.feature_store import RedisFeatureStore, create_feature_store
from src.serving.main import create_app
from src.serving.warmup_features import warmup
from src.search.queries import freeze_queries


def percentiles(samples: list[float]) -> dict:
    if not samples or not np.isfinite(samples).all():
        raise ValueError('nonempty finite latency samples required')
    values = np.asarray(np.percentile(samples, [50, 95, 99]))
    return {name: float(values[i]) for i, name in enumerate(('p50_ms', 'p95_ms', 'p99_ms'))}


def benchmark(cfg: dict) -> dict:
    if cfg['benchmark']['warmup'] < 10 or cfg['benchmark']['requests'] < 100 or cfg['benchmark']['concurrency'] != 1:
        raise ValueError('10 warmups and 100 serial requests are required')
    local = copy.deepcopy(cfg)
    local['serving'].setdefault('redis', {})['namespace'] = f'mm-recsys:b8:{uuid.uuid4().hex}'
    store = create_feature_store(local)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('actual Redis backend required for HTTP benchmark')
    warmup(local, store)
    folder = freeze_queries(cfg)
    queries = json.loads((folder / 'valid.json').read_text())
    app = create_app(local, feature_store=store)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0,
                                         log_level='error', loop='asyncio', lifespan='on'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    started = time.perf_counter()
    results = {}
    try:
        while not server.started:
            if not thread.is_alive() or time.perf_counter() - started > 60:
                raise RuntimeError('shared API failed to start with both compatible models')
            time.sleep(.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        startup_ms = (time.perf_counter() - started) * 1000
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
            health = client.get('/health')
            ready = client.get('/ready')
            if health.status_code != 200 or ready.status_code != 200:
                raise ValueError('both models must report ready')
            for mode in ('text', 'image', 'hybrid', 'recommendation'):
                payloads = []
                if mode != 'recommendation':
                    for query in (q for q in queries if q['mode'] == mode):
                        payload = dict(top_k=cfg['search']['top_k'])
                        if query['query_text']:
                            payload['query_text'] = query['query_text']
                        if query['query_image_path']:
                            payload['query_image'] = base64.b64encode((folder / query['query_image_path']).read_bytes()).decode()
                        payloads.append(payload)
                import pandas as pd
                users = sorted(pd.read_parquet(Path(cfg['paths']['data_dir']) / 'users.parquet').user_id.astype(str))
                samples, native, stages = [], [], []
                for i in range(cfg['benchmark']['warmup'] + cfg['benchmark']['requests']):
                    before = time.perf_counter()
                    response = (client.get('/api/recommend', params=dict(user_id=users[i % len(users)], top_n=cfg['recommend']['top_n']))
                                if mode == 'recommendation' else client.post('/api/search', json=payloads[i % len(payloads)]))
                    elapsed = (time.perf_counter() - before) * 1000
                    if response.status_code != 200:
                        raise ValueError(f'{mode}: HTTP {response.status_code}')
                    body = response.json()
                    if mode == 'recommendation':
                        parsed = RecommendResponse.model_validate(body)
                        pipeline = parsed.pipeline_latency.model_dump()
                        core = pipeline['total_ms']
                    else:
                        parsed_search = SearchResponse.model_validate(body)
                        if parsed_search.search_type != mode:
                            raise ValueError('search mode does not match the request')
                        core = parsed_search.latency_ms
                        pipeline = {}
                    if i >= cfg['benchmark']['warmup']:
                        samples.append(elapsed)
                        native.append(core)
                        stages.append(pipeline)
                results[mode] = dict(http=percentiles(samples), service=percentiles(native),
                    http_samples_ms=samples, service_samples_ms=native, stages=stages,
                    warmup=cfg['benchmark']['warmup'], requests=len(samples),
                    top_n=cfg['recommend']['top_n'] if mode == 'recommendation' else cfg['search']['top_k'], errors=0)
                print(f'B8 HTTP {mode}: p95={results[mode]["http"]["p95_ms"]:.3f}ms', flush=True)
            unknown = client.get('/api/recommend', params=dict(user_id='B8-unknown-cold-user', top_n=10))
            if unknown.status_code != 200:
                raise ValueError('unknown user cold-start fallback must return 200')
            RecommendResponse.model_validate(unknown.json())
            if client.post('/api/search', json={}).status_code != 422:
                raise ValueError('empty search must return 422')
        return dict(status='MEASURED', transport='actual localhost HTTP, persistent connection',
                    concurrency=1, model_startup_ms=startup_ms, health=health.json(), ready=ready.json(),
                    modes=results, config_fingerprint=fingerprint(cfg),
                    unknown_user_status=unknown.status_code, invalid_search_status=422,
                    store='C RedisFeatureStore with warmed observable profiles; isolated disposable namespace',
                    mab_scope='live Redis exposure/reward contract remains UNCONNECTED; offline/B7 adapter measurements are separate')
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        if thread.is_alive():
            raise RuntimeError('HTTP benchmark server did not shut down')
        keys = list(store.client.scan_iter(match=store.namespace + ':*'))
        if keys:
            store.client.delete(*keys)
        store.close()
