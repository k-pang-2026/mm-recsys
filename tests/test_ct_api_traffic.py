"""API demo outcomes must retain request attribution and retry identity."""
import io
import json
import time
from urllib.error import HTTPError

import pytest

from scripts.ct_api_traffic import visit
from src.ct.storage import Journal


class JournalAPI:
    def __init__(self, path, *, fail_after_write=False, request_id='r1'):
        self.journal = Journal(path)
        self.fail_after_write = fail_after_write
        self.request_id = request_id
        self.calls = []
        self.exposures = 0

    def open(self, request, timeout):
        if request.data is None:
            self.exposures += 1
            rid = f'r{self.exposures}'
            self.journal.exposure(rid, 'U000001', ['P000001', 'P000002'], 50, 'v1.0', time.time())
            result = dict(user_id='U000001', recommendations=[dict(product_id=p) for p in ['P000001', 'P000002']])
            response = io.BytesIO(json.dumps(result).encode())
            response.headers = {'X-Recommendation-Request-ID': rid if self.request_id else None}
            return response
        payload = json.loads(request.data)
        request_id = request.get_header('X-recommendation-request-id')
        self.calls.append((request.full_url, request_id, payload))
        applied = self.journal.event(payload, time.time(), request_id)
        if self.fail_after_write:
            self.fail_after_write = False
            raise HTTPError(request.full_url, 503, 'temporary store failure', {}, None)
        response = io.BytesIO(json.dumps(dict(applied=applied)).encode())
        response.headers = {}
        return response


@pytest.mark.parametrize(('index', 'views', 'purchases'), [(0, 0, 0), (1, 1, 0), (2, 1, 1)])
def test_visits_link_real_exposure_and_keep_session(tmp_path, index, views, purchases):
    api = JournalAPI(tmp_path / 'journal.sqlite3')
    records = []
    result = visit(api, 'http://api-server:8000', 'U000001', 'test-run', index, 50, records.append)
    assert result == dict(exposures=1, views=views, purchases=purchases)
    assert api.journal.count_since(0) == views + purchases
    assert all(rid == 'r1' and payload['product_id'] == 'P000001' for _, rid, payload in api.calls)
    assert len({payload['session_id'] for _, _, payload in api.calls}) <= 1
    if purchases:
        assert [url.rsplit('/', 1)[1] for url, _, _ in api.calls] == ['event', 'feedback']
    assert records[0]['event'] == 'exposure'
    assert len([r for r in records if r['event'] == 'intent']) == views + purchases


def test_partial_write_retry_preserves_event_id_and_attribution(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.ct_api_traffic.time.sleep', lambda _: None)
    api = JournalAPI(tmp_path / 'journal.sqlite3', fail_after_write=True)
    records = []
    visit(api, 'http://api-server:8000', 'U000001', 'test-run', 1, 50, records.append)
    assert len(api.calls) == 2
    assert api.calls[0] == api.calls[1]
    assert api.journal.count_since(0) == 1
    assert records[-1]['applied'] is False


def test_missing_request_header_never_sends_unattributed_outcome(tmp_path):
    api = JournalAPI(tmp_path / 'journal.sqlite3', request_id=None)
    with pytest.raises(ValueError, match='request ID'):
        visit(api, 'http://api-server:8000', 'U000001', 'test-run', 2, 50, lambda _: None)
    assert api.calls == []
    assert api.journal.count_since(0) == 0


def test_docker_simulator_collects_attributed_outcomes_by_default(tmp_path, monkeypatch):
    import pandas as pd
    from unittest.mock import Mock
    from docker import simulator
    from src.common.config import load_config
    from src.serving.feature_store import RedisFeatureStore
    cfg = load_config()
    cfg['paths'].update(data_dir=str(tmp_path), results_dir=str(tmp_path / 'results'))
    api = JournalAPI(tmp_path / 'journal.sqlite3')
    store = Mock(spec=RedisFeatureStore)
    monkeypatch.setenv('SIMULATOR_ATTRIBUTED_VISITS', '3')
    monkeypatch.setenv('CT_AUTO_TRAIN', '0')
    monkeypatch.setattr(simulator, 'runtime_config', lambda: cfg)
    monkeypatch.setattr(simulator, 'wait_ready', lambda *a: None)
    monkeypatch.setattr(simulator, 'create_feature_store', lambda _: store)
    monkeypatch.setattr(simulator, 'build_opener', lambda *a: api)
    monkeypatch.setattr(simulator.pd, 'read_parquet', lambda path: pd.DataFrame({'user_id':['U000001']}))
    monkeypatch.setattr(simulator, 'run_batch', lambda *a: dict(generated=100, ct_new_events=70))
    def stop(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(simulator.time, 'sleep', stop)
    with pytest.raises(KeyboardInterrupt):
        simulator.main()
    with api.journal.connect() as db:
        assert db.execute('SELECT count(*) FROM requests').fetchone()[0] == 3
        assert db.execute('SELECT count(*) FROM events WHERE request_id IS NOT NULL').fetchone()[0] == 3
    records = [json.loads(line) for line in next((tmp_path / 'results').glob('ct_api_traffic_*.jsonl')).read_text().splitlines()]
    assert all(row['synthetic'] is True for row in records)
    assert {r['mode'] for r in records if r['event'] == 'exposure'} == {'no_click','click_only','click_purchase'}
    store.close.assert_called_once()


@pytest.mark.parametrize('exited', [False, True])
def test_simulator_supervises_default_ct_worker_and_stops_its_group(tmp_path, monkeypatch, exited):
    import signal
    import pandas as pd
    from unittest.mock import Mock
    from docker import simulator
    from src.common.config import load_config
    from src.serving.feature_store import RedisFeatureStore
    cfg = load_config()
    cfg['paths'].update(data_dir=str(tmp_path), results_dir=str(tmp_path / 'results'))
    store = Mock(spec=RedisFeatureStore)
    worker = Mock(pid=12345, returncode=7 if exited else None)
    worker.poll.return_value = 7 if exited else None
    launch, killed = [], []
    monkeypatch.delenv('CT_AUTO_TRAIN', raising=False)
    monkeypatch.setenv('SIMULATOR_ATTRIBUTED_VISITS', '0')
    monkeypatch.setattr(simulator, 'runtime_config', lambda: cfg)
    monkeypatch.setattr(simulator, 'wait_ready', lambda *a: None)
    monkeypatch.setattr(simulator, 'create_feature_store', lambda _: store)
    monkeypatch.setattr(simulator.pd, 'read_parquet', lambda _: pd.DataFrame({'user_id':['U000001']}))
    monkeypatch.setattr(simulator, 'run_batch', lambda *a: dict(generated=100, ct_new_events=70))
    monkeypatch.setattr(simulator.subprocess, 'Popen', lambda args, **kw: launch.append((args, kw)) or worker)
    monkeypatch.setattr(simulator.os, 'killpg', lambda pid, sig: killed.append((pid, sig)), raising=False)
    def stop(_):
        raise KeyboardInterrupt
    monkeypatch.setattr(simulator.time, 'sleep', stop)
    with pytest.raises(RuntimeError if exited else KeyboardInterrupt):
        simulator.main()
    assert launch[0][0][-2:] == ['-m', 'docker.ct_worker']
    assert launch[0][1]['start_new_session'] is True
    assert killed == ([] if exited else [(12345, signal.SIGTERM)])
    store.close.assert_called_once()
