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
from docker.simulator import read_checkpoint, send_rows
from scripts import prepare_all
from src.common.config import load_config
from src.search.locking import writer_lock


def test_compose_defaults_to_full_and_replay_waits_for_dashboard():
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


def test_stream_retries_keep_event_ids_and_stop_at_failed_feedback(monkeypatch):
    import docker.simulator as simulator
    frame = pd.DataFrame([
        dict(event_id='skip', user_id='u', product_id=None, event_type='search', session_id='s'),
        dict(event_id='e1', user_id='u', product_id='p', event_type='view', session_id='s'),
        dict(event_id='e2', user_id='u', product_id='p', event_type='purchase', session_id='s')])
    calls = []
    def failed(url, payload):
        calls.append((url, payload.copy()))
        if url.endswith('/feedback'):
            raise ConnectionError('offline')
        return {'applied': True}
    monkeypatch.setattr(simulator, 'request', failed)
    with pytest.raises(ConnectionError):
        send_rows('http://api', frame, {'p': 'category'})
    assert [v['event_id'] for _, v in calls] == ['e1', 'e1']
    monkeypatch.setattr(simulator, 'request', lambda url, payload: calls.append((url, payload.copy())))
    send_rows('http://api', frame, {'p': 'category'})
    assert [v['event_id'] for _, v in calls[2:]] == ['e1', 'e1', 'e2', 'e2']
    assert calls[2][1]['category'] == 'category'


def test_replay_checkpoint_follows_redis_state_not_a_former_backend():
    import fakeredis
    first, fresh = fakeredis.FakeRedis(decode_responses=True), fakeredis.FakeRedis(decode_responses=True)
    first.set('checkpoint', json.dumps(dict(data_fingerprint='frozen', offset=100)))
    assert read_checkpoint(first, 'checkpoint', 'frozen', 200)['offset'] == 100
    assert read_checkpoint(fresh, 'checkpoint', 'frozen', 200)['offset'] == 0
    first.set('checkpoint', json.dumps(dict(data_fingerprint='other', offset=100)))
    with pytest.raises(ValueError, match='frozen dataset'):
        read_checkpoint(first, 'checkpoint', 'frozen', 200)


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
