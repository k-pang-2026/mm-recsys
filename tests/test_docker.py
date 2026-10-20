from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import threading
import urllib.error
import urllib.request

import pandas as pd
import pytest

from docker.api_entrypoint import PreparingHandler, PreparationServer
from docker.http import wait_ready
from docker.runtime import runtime_config
from docker.simulator import generate_batch, run_batch
from scripts import prepare_all
from src.common.config import load_config
from src.search.locking import writer_lock


def test_compose_defaults_to_full_and_simulator_waits_for_dashboard():
    import yaml
    from dotenv import dotenv_values
    cfg = yaml.safe_load(Path('docker-compose.yml').read_text())
    assert dotenv_values('.env')['SCALE'] == 'full'
    for name in ('api-server', 'dashboard', 'simulator'):
        service = cfg['services'][name]
        assert service['environment']['SCALE'] == '${SCALE:-full}'
        assert service['pull_policy'] == 'build'
    dashboard = cfg['services']['dashboard']
    assert dashboard['healthcheck']['start_period'] == '${READY_TIMEOUT_SECONDS:-21600}s'
    assert cfg['services']['simulator']['depends_on']['dashboard']['condition'] == 'service_healthy'


def test_dashboard_connects_to_api_before_launch_and_announces_after_http(monkeypatch, capsys):
    from docker import dashboard_entrypoint as entry
    events = []
    process = SimpleNamespace(returncode=None, poll=lambda: process.returncode)
    def finished(*args, **kwargs):
        process.returncode = 0
        return 0
    process.wait = finished
    def connected(*args):
        events.append('api_ready')
    def launched(argv):
        assert events == ['api_ready']
        events.append('launch')
        return process
    class Health:
        def __enter__(self):
            events.append('http_ready')
            return SimpleNamespace(status=200)
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(entry, 'wait_ready', connected)
    monkeypatch.setattr(entry.subprocess, 'Popen', launched)
    monkeypatch.setattr(entry.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=lambda *a, **kw: Health()))
    monkeypatch.setenv('PUBLIC_DASHBOARD_URL', 'http://localhost:18501')
    assert entry.main() == 0
    assert events == ['api_ready', 'launch', 'http_ready']
    assert 'http://localhost:18501 에서 대시보드 시작' in capsys.readouterr().out


def test_dashboard_failure_never_announces_success(monkeypatch, capsys):
    from docker import dashboard_entrypoint as entry
    process = SimpleNamespace(returncode=1, poll=lambda: 1)
    monkeypatch.setattr(entry, 'wait_ready', lambda *args: None)
    monkeypatch.setattr(entry.subprocess, 'Popen', lambda *args: process)
    with pytest.raises(RuntimeError, match='준비 전에 종료'):
        entry.main()
    assert '에서 대시보드 시작' not in capsys.readouterr().out


def test_parallel_hybrid_overlaps_towers_and_preserves_fusion(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np
    import docker.serve as serving
    from src.search.build_index import fuse
    barrier = threading.Barrier(2, timeout=5)
    text = np.array([[1., 0.]], dtype=np.float32)
    image = np.array([[0., 1.]], dtype=np.float32)
    class Encoder:
        def encode_texts(self, values):
            assert values == ['query']; barrier.wait(); return text
        def encode_images(self, values):
            assert values == ['image']; barrier.wait(); return image
    original = SimpleNamespace(encoder=Encoder(), _lock=threading.RLock(), cfg=runtime_config())
    monkeypatch.setattr(serving, 'apply_budget', lambda threads: None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        mode, vector = serving.ParallelHybridSearcher(original, pool, 2).encode('query', 'image')
    assert mode == 'hybrid'
    np.testing.assert_array_equal(vector, fuse(text, image, original.cfg['search']['query_fusion']))


def test_parallel_failure_joins_image_job_before_request_cleanup(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    import docker.serve as serving
    entered, release = threading.Event(), threading.Event()
    class Encoder:
        def encode_texts(self, values):
            assert entered.wait(5); raise ValueError('failed text')
        def encode_images(self, values):
            entered.set(); assert release.wait(5); return None
    original = SimpleNamespace(encoder=Encoder(), _lock=threading.RLock(), cfg=runtime_config())
    monkeypatch.setattr(serving, 'apply_budget', lambda threads: None)
    with ThreadPoolExecutor(max_workers=2) as pool, ThreadPoolExecutor(max_workers=1) as caller:
        result = caller.submit(serving.ParallelHybridSearcher(original, pool, 2).encode, 'query', 'image')
        try:
            assert entered.wait(5)
            with pytest.raises(TimeoutError):
                result.result(timeout=.05)
        finally:
            release.set()
        with pytest.raises(ValueError, match='failed text'):
            result.result(timeout=5)


def test_preparation_health_is_live_but_not_ready():
    server = PreparationServer(('127.0.0.1', 0), PreparingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(url + '/health') as response:
            assert response.status == 200 and json.load(response)['search_ready'] is False
        for route in ('/ready', '/api/recommend?user_id=u'):
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url + route)
            assert caught.value.code == 503
        with pytest.raises(TimeoutError, match='timed out'):
            wait_ready(url, timeout=.02, interval=.001)
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_runtime_does_not_mutate_role_configuration():
    original = load_config()
    runtime = runtime_config(original)
    assert original['paths']['results_dir'] == 'docs/results'
    assert runtime['paths']['results_dir'] == 'docs/results/docker/runtime/dev'
    assert runtime['recommend'] == original['recommend'] and runtime['targets'] == original['targets']


def test_container_source_paths_map_only_inside_checkout():
    from docker.verify_evidence import local_path
    assert local_path('/app/scripts/smoke_test.py') == Path('scripts/smoke_test.py')
    with pytest.raises(ValueError):
        local_path('/etc/passwd')
    with pytest.raises(ValueError):
        local_path('../foreign.py')


def test_complete_clip_cache_needs_no_network(monkeypatch):
    import huggingface_hub
    def local(repo, name, **kwargs):
        assert kwargs['local_files_only'] is True
        return '/cache/' + name
    def network(*args, **kwargs):
        raise AssertionError('complete cache must work offline')
    monkeypatch.setattr(huggingface_hub, 'hf_hub_download', local)
    monkeypatch.setattr(huggingface_hub, 'snapshot_download', network)
    prepare_all.prefetch(runtime_config())


def test_process_budget_applies_after_both_factories(tmp_path):
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from docker.serve import install_runtime_limits
    import faiss
    import torch
    import gc
    old_torch, old_faiss = torch.get_num_threads(), faiss.omp_get_max_threads()
    cfg = runtime_config(); cfg['paths']['results_dir'] = str(tmp_path)
    cfg['search']['torch_threads'] = 1
    class FakeBackend:
        data = {'catalog': 'unchanged'}
        def recommend(self, uid, top_n):
            return dict(threads=torch.get_num_threads(), faiss_threads=faiss.omp_get_max_threads())
    @asynccontextmanager
    async def loaders(application):
        torch.set_num_threads(4); faiss.omp_set_num_threads(4)
        application.state.recommend = FakeBackend()
        yield
    shared = FastAPI(lifespan=loaders)
    @shared.post('/api/admin/reload')
    def reload_bundle():
        torch.set_num_threads(4); faiss.omp_set_num_threads(4)
        shared.state.recommend = FakeBackend()
        return dict(status='reloaded')
    @shared.get('/threads')
    def thread_count():
        return shared.state.recommend.recommend('u', 1)
    install_runtime_limits(shared, cfg)
    try:
        with TestClient(shared) as client:
            evidence = json.loads((tmp_path / 'serving_runtime.json').read_text())
            assert evidence['torch_threads'] == evidence['faiss_threads'] == 1
            assert evidence['gc_enabled'] and evidence['gc_frozen_objects'] > 0
            assert shared.state.recommend.data == {'catalog': 'unchanged'}
            assert client.get('/threads').json() == dict(threads=1, faiss_threads=1)
            assert client.post('/api/admin/reload', json={}).json()['status'] == 'reloaded'
            assert client.get('/threads').json() == dict(threads=1, faiss_threads=1)
    finally:
        torch.set_num_threads(old_torch); faiss.omp_set_num_threads(old_faiss)


def test_prepare_failure_stops_dependents_and_records_real_exit(tmp_path, monkeypatch):
    cfg = runtime_config()
    cfg['paths'].update(model_dir=str(tmp_path / 'models'), results_dir=str(tmp_path / 'results'))
    called = []
    def child(command, **kwargs):
        called.append(command[-1])
        return SimpleNamespace(returncode=9 if command[-1] == 'embeddings' else 0)
    monkeypatch.setattr(prepare_all.subprocess, 'run', child)
    with pytest.raises(RuntimeError, match='embeddings: exit 9'):
        prepare_all.prepare(cfg)
    assert called == ['data', 'embeddings']
    result = json.loads((tmp_path / 'results/preparation.json').read_text())
    assert result['status'] == 'FAIL' and result['stages'][-1]['exit_code'] == 9


def test_prepare_lock_prevents_two_initial_writers(tmp_path):
    cfg = runtime_config(); cfg['paths']['model_dir'] = str(tmp_path)
    with writer_lock(tmp_path / '.docker/prepare.lock'):
        with pytest.raises(ValueError, match='another process'):
            prepare_all.prepare(cfg)


def test_partial_recommendation_is_preserved_and_rejected(tmp_path):
    cfg = runtime_config(); cfg['paths']['model_dir'] = str(tmp_path)
    folder = tmp_path / 'v1.0'; folder.mkdir()
    (folder / 'two_tower.pt').write_bytes(b'partial training evidence')
    before = (folder / 'two_tower.pt').read_bytes()
    with pytest.raises(ValueError, match='Incomplete recommendation'):
        prepare_all.stage(cfg, 'recommendation')
    assert (folder / 'two_tower.pt').read_bytes() == before
    assert list(folder.iterdir()) == [folder / 'two_tower.pt']


@pytest.fixture
def live_catalog(tmp_path):
    import numpy as np
    from src.simulator.catalog import make_catalog
    from src.simulator.users import make_users
    cfg = load_config()
    cfg['paths']['data_dir'] = str(tmp_path)
    cfg['simulator'].update(n_products=450, n_users=120, n_events=4000)
    (tmp_path / 'split_manifest.json').write_text(json.dumps({'generation_fingerprint': 'frozen'}))
    rng = np.random.default_rng(cfg['seed'])
    return cfg, make_catalog(cfg, rng), make_users(cfg, rng)


def test_live_generator_has_new_ids_and_preserves_configured_behavior(live_catalog):
    import copy
    import numpy as np
    cfg, products, users = live_catalog
    before = copy.deepcopy(cfg)
    first = generate_batch(cfg, products, users, np.random.default_rng(42), 100)
    second = generate_batch(cfg, products, users, np.random.default_rng(42), 100)
    assert cfg == before
    assert len(first) == 100 and first.event_id.is_unique
    assert set(first.event_type) == {'search', 'view', 'cart', 'purchase'}
    assert all(value.startswith('live-') for value in first.event_id)
    assert not set(first.event_id) & set(second.event_id)
    assert first.user_id.nunique() == 1
    pd.testing.assert_series_equal(first.product_id, second.product_id)
    pd.testing.assert_series_equal(first.event_type, second.event_type)
    assert first.timestamp.is_monotonic_increasing and first.generated_at.notna().all()


def test_live_batch_updates_redis_without_reading_or_posting_frozen_events(live_catalog, monkeypatch):
    import fakeredis
    import numpy as np
    import docker.http
    from src.serving.feature_store import RedisFeatureStore
    cfg, products, users = live_catalog
    def no_post(*args, **kwargs):
        raise AssertionError('live simulator must not POST frozen events to the API')
    monkeypatch.setattr(docker.http, 'request', no_post)
    store = RedisFeatureStore(fakeredis.FakeRedis(decode_responses=True))
    result = run_batch(cfg, store, products, users, np.random.default_rng(42), 100)
    frame = pd.read_parquet(result['source'])
    assert result['generated'] == 100 and result['features_processed'] > 0
    assert not Path(cfg['paths']['data_dir'], 'events.parquet').exists()
    assert not Path(result['source']).with_name('pending.parquet').exists()
    supported = frame[frame.event_type.isin(['view', 'cart', 'purchase'])]
    last_session = supported[supported.session_id == supported.session_id.iloc[-1]]
    features = store.get_features(supported.user_id.iloc[-1])
    expected = last_session[last_session.event_type == 'view'].product_id.tolist()
    assert features.recent_clicks == expected[-store.history_limit:]
    assert features.session_clicks == len(expected)


def test_failed_live_batch_preserves_pending_ids_and_retries_without_duplicate_rewards(live_catalog, monkeypatch):
    import fakeredis
    import numpy as np
    import docker.simulator as simulator
    from src.serving.feature_store import RedisFeatureStore
    cfg, products, users = live_catalog
    product = products.product_id.iloc[0]
    frame = pd.DataFrame([dict(event_id='live-e1', user_id='u', product_id=product,
                              event_type='view', session_id='live-s'),
                          dict(event_id='live-e2', user_id='u', product_id=product,
                              event_type='purchase', session_id='live-s')])
    class InterruptedStore(RedisFeatureStore):
        fail = True
        def update_reward(self, feedback):
            if feedback.event_id == 'live-e2' and self.fail:
                self.fail = False
                raise ConnectionError('interrupted')
            return super().update_reward(feedback)
    store = InterruptedStore(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(simulator, 'generate_batch', lambda *args: frame)
    with pytest.raises(ConnectionError, match='interrupted'):
        run_batch(cfg, store, products, users, np.random.default_rng(42), 100)
    folder = Path(cfg['paths']['data_dir'], 'stream/live/frozen')
    assert (folder / 'pending.parquet').exists() and not list(folder.glob('events-*.parquet'))
    monkeypatch.setattr(simulator, 'generate_batch', lambda *args: pytest.fail('pending IDs must be reused'))
    result = run_batch(cfg, store, products, users, np.random.default_rng(42), 100)
    assert result['generated'] == 2 and (folder / 'pending.parquet').exists() is False
    assert store.get_features('u').recent_clicks == [product]
    assert store.client.hgetall(store.key('reward', product)) == {'clicks': '1', 'purchases': '1'}
    assert pd.read_parquet(result['source']).event_id.tolist() == ['live-e1', 'live-e2']


@pytest.fixture
def measurement_fixture():
    cfg = runtime_config()
    series = [1.] * 100
    modes = {mode: dict(http_samples_ms=list(series), warmup=10, requests=100, errors=0,
                       http=dict(p95_ms=1.)) for mode in ('text', 'image', 'hybrid', 'recommendation')}
    smoke = dict(status='PASS', scale='dev', data_fingerprint='dataset',
        checks={key: 'PASS' for key in ('api_schemas', 'multipart', 'invalid_search', 'session_response', 'dashboard_http')},
        benchmark=dict(environment=dict(docker=True), modes=modes,
            feature=dict(warmup=10, requests=100, samples_ms=list(series), data_fingerprint='dataset'),
            candidate=dict(warmup=10, calls=100, elapsed_ms=list(series), candidate_count_min=300,
                           data_fingerprint='dataset')))
    prep = dict(status='PASS', scale='dev', data_fingerprint='dataset', stages=[dict(exit_code=0) for _ in range(5)])
    return cfg, smoke, prep, dict(generation_fingerprint='dataset')


def test_evidence_recomputes_latency_instead_of_trusting_pass(measurement_fixture):
    from docker.verify_evidence import verify
    cfg, smoke, prep, manifest = measurement_fixture
    verify(cfg, smoke, prep, manifest)
    smoke['benchmark']['modes']['hybrid']['http_samples_ms'] = [999.] * 100
    with pytest.raises(ValueError, match='latency mismatch'):
        verify(cfg, smoke, prep, manifest)


def test_evidence_rejects_short_samples_and_foreign_data(measurement_fixture):
    from docker.verify_evidence import verify
    cfg, smoke, prep, manifest = measurement_fixture
    smoke['data_fingerprint'] = 'foreign'
    with pytest.raises(ValueError, match='fingerprint'):
        verify(cfg, smoke, prep, manifest)
    smoke['data_fingerprint'] = 'dataset'
    smoke['benchmark']['candidate']['elapsed_ms'].pop()
    with pytest.raises(ValueError, match='candidate samples'):
        verify(cfg, smoke, prep, manifest)
