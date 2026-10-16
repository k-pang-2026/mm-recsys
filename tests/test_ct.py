from __future__ import annotations

from pathlib import Path
import shutil
import threading

import pytest
from fastapi.testclient import TestClient

from src.common.config import load_config
from src.ct.monitor import measure, monitor
from src.ct.retrain_trigger import components, settings, trigger
from src.ct.storage import Journal, file_lock
from src.recommendation.testing import service_fixture
from src.serving.main import create_app
from src.serving.memory_store import MemoryFeatureStore
from src.serving.model_loader import load_record


def config(tmp_path):
    cfg = load_config()
    cfg['paths'].update(model_dir=str(tmp_path / 'models'), results_dir=str(tmp_path / 'results'))
    cfg['serving']['ct'].update(retrain_log_threshold=3, min_mature_requests=1,
                               attribution_seconds=10, recent_seconds=100)
    return cfg


def event(i='e', **extra):
    return dict(event_id=i, user_id='u', product_id='p', event_type='view', **extra)


def test_attribution_maturity_dedup_and_alert(tmp_path):
    journal = Journal(tmp_path / 'events.sqlite3'); cfg = config(tmp_path); spec = settings(cfg)
    spec.update(ctr_threshold=.6, hitrate_threshold=.5)
    journal.exposure('r', 'u', ['p', 'q'], 50, 'v1.0', 10.)
    journal.exposure('immature', 'u', ['p'], 10, 'v1.0', 25.)
    assert journal.event(event(), 11., 'r', 10)
    assert not journal.event(event(), 11., 'r', 10)
    for payload, at, request in [(event('x',), 9., 'r'),
                                  (dict(event('x'), user_id='other'), 12., 'r'),
                                  (dict(event('x'), product_id='other'), 12., 'r'),
                                  (event('x'), 21., 'r'), (event('x'), 12., 'absent')]:
        with pytest.raises(ValueError, match='unattributable'):
            journal.event(payload, at, request, 10)
    value = monitor(journal, spec, 30., tmp_path / 'ct_log.jsonl')
    assert value['exposures'] == 2 and value['ctr'] == .5
    assert value['hit_rate_at_50'] == 0 and len(value['alerts']) == 2
    assert len((tmp_path / 'ct_log.jsonl').read_text().splitlines()) == 1
    assert journal.event(dict(event('buy'), event_type='purchase'), 13., 'r', 10)
    assert measure(journal, spec, 30.)['hit_rate_at_50'] == 1.
    assert measure(journal, spec, 200.)['ctr'] is None


def test_top10_and_unlinked_events_never_fabricate_hitrate_or_clicks(tmp_path):
    journal = Journal(tmp_path / 'events.sqlite3'); spec = settings(config(tmp_path))
    journal.exposure('r', 'u', ['p'], 10, 'v1.0', 10.)
    journal.event(event(), 11.)
    result = measure(journal, spec, 30.)
    assert result['ctr'] == 0 and result['hit_rate_at_50'] is None
    assert result['top50_requests'] == 0 and journal.high_watermark() == 1


@pytest.fixture
def registry_fixture(tmp_path, monkeypatch):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR', raising=False)
    cfg, _ = service_fixture(tmp_path)
    cfg['paths']['results_dir'] = str(tmp_path / 'results')
    cfg['serving']['ct'].update(retrain_log_threshold=3, min_mature_requests=1)
    _, journal, registry = components(cfg)
    registry.register('v1.0', cfg, Path(cfg['paths']['data_dir']), {}, None, 0)
    registry.initialize('v1.0')
    return cfg, journal, registry


def comparison(before=.5, after=.8, split='valid'):
    return dict(baseline=dict(ctr_auc=before), candidate=dict(ctr_auc=after), split=split,
                validation_fingerprint='controlled-fixture-cohort')


def copy_version(registry, version):
    shutil.copytree(registry.root / 'v1.0', registry.root / version)


def test_registry_increment_reject_rollback_and_tamper(registry_fixture):
    cfg, _, registry = registry_fixture
    assert registry.next_version() == 'v1.1'
    copy_version(registry, 'v1.1')
    registry.register('v1.1', cfg, Path(cfg['paths']['data_dir']), {}, 'v1.0', 3)
    assert registry.decide('v1.1', comparison(), settings(cfg))
    assert registry.read()['active'] == 'v1.1' and registry.read()['last_success_seq'] == 3
    copy_version(registry, 'v1.2')
    registry.register('v1.2', cfg, Path(cfg['paths']['data_dir']), {}, 'v1.1', 6)
    assert not registry.decide('v1.2', comparison(.8, .79), settings(cfg))
    assert registry.read()['active'] == 'v1.1'
    with pytest.raises(ValueError):
        registry.rollback('v1.1', 'v1.2', 'rejected is not a rollback target')
    registry.rollback('v1.1', 'v1.0', 'controlled fixture rollback')
    assert registry.read()['active'] == 'v1.0'
    (registry.root / 'v1.0' / 'ranking/deepfm.pt').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='changed'):
        registry.verify('v1.0')


@pytest.mark.parametrize('after,split', [(float('nan'), 'valid'), (.9, 'test'), (None, 'valid'), (.5001, 'valid')])
def test_promotion_requires_finite_valid_improvement(registry_fixture, after, split):
    cfg, _, registry = registry_fixture; copy_version(registry, 'v1.1')
    registry.register('v1.1', cfg, Path(cfg['paths']['data_dir']), {}, 'v1.0', 3)
    assert not registry.decide('v1.1', comparison(after=after, split=split), settings(cfg))
    assert registry.read()['active'] == 'v1.0'


def test_threshold_failures_retry_captured_watermark_and_concurrent_lock(registry_fixture):
    cfg, journal, registry = registry_fixture
    assert trigger(cfg, lambda *args: pytest.fail('premature training'))['status'] == 'WAITING'
    for i in range(3):
        journal.event(event(str(i)), float(i))
    with file_lock(registry.root / '.ct/training.lock'):
        assert trigger(cfg, lambda *args: pytest.fail('concurrent training'))['status'] == 'BUSY'
    def fail(*args):
        raise RuntimeError('training interrupted')
    with pytest.raises(RuntimeError):
        trigger(cfg, fail)
    assert registry.read()['last_success_seq'] == 0
    def build(version, through, reg):
        assert through == 3
        journal.event(event('arrived-during-training'), 10.)
        copy_version(reg, version)
        return dict(config=cfg, data_path=cfg['paths']['data_dir'], comparison=comparison())
    assert trigger(cfg, build)['status'] == 'PROMOTED'
    assert journal.count_since(registry.read()['last_success_seq']) == 1
    assert trigger(cfg, fail)['status'] == 'WAITING'


def test_reload_internal_only_and_failed_preload_preserves_pointer(registry_fixture, monkeypatch):
    cfg, _, registry = registry_fixture
    store = MemoryFeatureStore(); initial = load_record(registry, 'v1.0', store)
    app = create_app(cfg, recommend_service=initial, feature_store=store)
    with TestClient(app) as client:
        assert client.post('/api/admin/reload', json={}).status_code == 403
        assert client.post('/api/admin/reload', json={}, headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 403
        response = client.get('/api/recommend', params={'user_id': 'u'})
        rid = response.headers['X-Recommendation-Request-ID']
        payload = dict(event('linked'), product_id=response.json()['recommendations'][0]['product_id'])
        assert client.post('/api/feedback', json=payload, headers={'X-Recommendation-Request-ID': rid}).status_code == 200
        assert client.post('/api/feedback', json=dict(payload, event_id='wrong', user_id='other'),
                           headers={'X-Recommendation-Request-ID': rid}).status_code == 422
    from src.serving import ct_admin
    from starlette.requests import Request
    request = Request({'type': 'http', 'client': ('127.0.0.1', 5000), 'app': app, 'headers': []})
    before = app.state.recommend
    (registry.root / 'v1.0' / 'ranking/deepfm.pt').write_bytes(b'corrupt')
    with pytest.raises(Exception) as error:
        ct_admin.reload_model(ct_admin.ReloadRequest(), request)
    assert error.value.status_code == 409 and app.state.recommend is before


def test_atomic_reload_allows_old_inflight_request_to_finish(registry_fixture, monkeypatch):
    from src.serving import ct_admin
    from starlette.requests import Request
    cfg, _, registry = registry_fixture; store = MemoryFeatureStore()
    initial = load_record(registry, 'v1.0', store)
    copy_version(registry, 'v1.1')
    registry.register('v1.1', cfg, Path(cfg['paths']['data_dir']), {}, 'v1.0', 3)
    registry.decide('v1.1', comparison(), settings(cfg))
    app = create_app(cfg, recommend_service=initial, feature_store=store)
    with TestClient(app):
        entered = threading.Event(); release = threading.Event(); output = []
        def old_request():
            captured = app.state.recommend; entered.set(); release.wait(5)
            output.append(captured.recommend('u', 10))
        worker = threading.Thread(target=old_request); worker.start(); assert entered.wait(5)
        request = Request({'type': 'http', 'client': ('127.0.0.1', 5000), 'app': app, 'headers': []})
        assert ct_admin.reload_model(ct_admin.ReloadRequest(), request)['version'] == 'v1.1'
        assert app.state.recommend is not initial and app.state.recommend.store is store
        release.set(); worker.join(5)
        assert len(output[0].recommendations) == 10
        assert len(app.state.recommend.recommend('u', 10).recommendations) == 10
        registry.rollback('v1.1', 'v1.0', 'test')
        assert ct_admin.reload_model(ct_admin.ReloadRequest(), request)['version'] == 'v1.0'


def test_fresh_snapshot_checks_hashes_and_keeps_timestamp_groups(tmp_path):
    import json
    import pandas as pd
    from src.common.artifacts import file_hash
    from src.ct.training import snapshot
    cfg, data = service_fixture(tmp_path)
    source = Path(cfg['paths']['data_dir'])
    events = pd.concat([data['train'], data['valid']], ignore_index=True)
    # More distinct times make all splits nonempty; an exact timestamp group must stay together.
    extra = data['valid'].copy(); extra['event_id'] = 'extra'
    extra['timestamp'] += pd.Timedelta(days=1)
    events = pd.concat([events, extra], ignore_index=True)
    impressions = pd.DataFrame(dict(impression_id=['i'], request_id=['r'], user_id=['u'],
                                   product_id=['p00'], exposed_at=[events.timestamp.min()], position=[1]))
    before = file_hash(source / 'split/train.parquet')
    manifest = snapshot(source, tmp_path / 'new-data', events, impressions, cfg)
    assert manifest['parent_fingerprint'] == data['manifest']['generation_fingerprint']
    assert sum(manifest['split_counts'].values()) == len(events)
    assert file_hash(source / 'split/train.parquet') == before
    parts = [pd.read_parquet(tmp_path / f'new-data/split/{name}.parquet') for name in ('train', 'valid', 'test')]
    assert parts[0].timestamp.max() < parts[1].timestamp.min() <= parts[1].timestamp.max() < parts[2].timestamp.min()
    with pytest.raises(ValueError, match='duplicate'):
        snapshot(source, tmp_path / 'duplicate', pd.concat([events, events.iloc[:1]]), impressions, cfg)
    (source / 'users.parquet').write_bytes(b'bad')
    with pytest.raises(ValueError, match='checksum'):
        snapshot(source, tmp_path / 'bad-source', events, impressions, cfg)


def test_default_trigger_is_10000_and_empty_exposure_is_not_an_error(tmp_path):
    cfg = load_config()
    assert settings(cfg)['retrain_log_threshold'] == 10000
    journal = Journal(tmp_path / 'journal.sqlite3')
    journal.exposure('empty-cold-start', 'u', [], 10, 'v1.0', 10.)
    assert measure(journal, settings(config(tmp_path)), 30.)['ctr'] is None


@pytest.mark.parametrize('url', ['https://example.com', 'http://api-server:8000',
                                 'http://127.0.0.1.evil.test', 'http://127.0.0.1:8000/path',
                                 'http://user:pass@127.0.0.1', 'http://127.0.0.1?x=y'])
def test_reload_client_only_allows_direct_loopback_origin(url):
    from src.ct.retrain_trigger import reload_api
    with pytest.raises(ValueError, match='local HTTP'):
        reload_api(url, 'v1.0')
