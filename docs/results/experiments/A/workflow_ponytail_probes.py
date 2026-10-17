"""Report-only audit reproductions. No live Redis, models or API are modified.

Run: PYTHONPATH=. .venv/bin/python docs/results/experiments/A/workflow_ponytail_probes.py
These assertions confirm existing defects; passing does not mean they are fixed.
"""
from __future__ import annotations

import asyncio
import argparse
import base64
import copy
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd
from PIL import Image
from fastapi.testclient import TestClient

from src.common.config import load_config
from src.common.schemas import SearchRequest, UserFeatures
from src.ct.storage import Journal
from src.recommendation.ranking_labels import build_labels
from src.recommendation.reranking import RankedItem, Reranker


def run() -> dict:
    cfg = load_config()
    observed: dict = {}
    at = pd.Timestamp('2026-01-01', tz='UTC')
    products = pd.DataFrame([dict(product_id=f'p{i}', category_l2='same',
                                 category_l3='same', created_at=at) for i in range(5)])
    items, diagnostics = Reranker(cfg, products).run(
        [RankedItem(f'p{i}', 1-i/10) for i in range(5)], 5, at, 10,
        {}, {}, lambda p: p, np.random.default_rng(42))
    assert len(items) == 5 and 'diversity' in diagnostics['violations']
    assert diagnostics['diversity_feasible_for_returned'] is False
    observed['diversity'] = diagnostics

    with tempfile.TemporaryDirectory(prefix='ponytail-audit-') as tmp:
        journal = Journal(Path(tmp) / 'journal.sqlite3')
        journal.exposure('request1', 'u1', ['p1'], 1, 'v1.0', at.timestamp())
        for index in range(2):
            assert journal.event(dict(event_id=f'click{index}', user_id='u1', product_id='p1',
                event_type='view', session_id='s1'), at.timestamp()+index+1, 'request1', 1800)
        with journal.connect() as db:
            rows = db.execute('SELECT * FROM events ORDER BY seq').fetchall()
        # Use the exact request/product mapping from build_from_journal.
        events = pd.DataFrame([dict(event_id=r['id'], user_id=r['user_id'],
            product_id=r['product_id'], event_type=r['kind'], session_id='s1',
            timestamp=pd.Timestamp(r['at'], unit='s', tz='UTC'),
            impression_id=f"{r['request_id']}:{r['product_id']}") for r in rows])
        exposures = pd.DataFrame([dict(impression_id='request1:p1', request_id='request1',
            user_id='u1', product_id='p1', exposed_at=at, position=1)])
        try:
            build_labels(exposures, events, at, at+pd.Timedelta(hours=1), 1800)
        except ValueError as error:
            assert 'multiple views for an impression' in str(error)
            observed['repeated_clicks'] = dict(journal_accepted=len(rows), error=str(error))
        else:
            raise AssertionError('expected repeated-click rejection')

    from src.serving.main import create_app

    class TransientFailureStore:
        available = True

        def append_event(self, event):
            self.available = False
            return False

        def get_features(self, user_id):
            self.available = True  # Redis recovers before the later feature read.
            return UserFeatures()

    local = copy.deepcopy(cfg)
    local['serving']['ct']['enabled'] = False
    with TestClient(create_app(cfg=local, search_service=object(), recommend_service=object(),
                               feature_store=TransientFailureStore())) as client:
        response = client.post('/api/event', json=dict(event_id='e1', user_id='u1',
            product_id='p1', event_type='view'))
        assert response.status_code == 200 and response.json()['applied'] is False
        observed['redis_event_failure'] = dict(status=response.status_code, response=response.json())
    from docker.simulator import send_rows
    with patch('docker.simulator.request', return_value={'applied': False}) as request:
        send_rows('http://unused', pd.DataFrame([dict(event_id='e1', user_id='u1',
            product_id='p1', event_type='view', session_id='s1')]), {})
        assert request.call_count == 2
        observed['redis_event_failure']['simulator_returns_normally'] = True

    from src.ct import retrain_trigger
    registry = SimpleNamespace(log=Path('/unused'))
    with (redirect_stdout(StringIO()),
          patch('sys.argv', ['audit', '--watch', '--train', '--reload-url', 'http://127.0.0.1:8000']),
          patch.object(retrain_trigger, 'load_config', return_value=cfg),
          patch.object(retrain_trigger, 'components', return_value=({'poll_seconds': 1}, object(), registry)),
          patch('src.ct.monitor.monitor'),
          patch.object(retrain_trigger, 'trigger', return_value={'status': 'PROMOTED', 'active': 'v1.1'}) as trigger,
          patch.object(retrain_trigger, 'reload_api', side_effect=RuntimeError('temporary HTTP 503')) as reload,
          patch.object(retrain_trigger.time, 'sleep') as sleep):
        try:
            retrain_trigger.main()
        except RuntimeError as error:
            assert reload.call_count == trigger.call_count == 1 and sleep.call_count == 0
            observed['ct_reload_failure'] = dict(error=str(error), retries=0, watch_loop_exited=True)
        else:
            raise AssertionError('expected watch loop to stop')

    image = Image.new('L', (12000, 12000))
    encoded = BytesIO()
    image.save(encoded, format='PNG')
    image.close()
    raw = encoded.getvalue()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        payload = dict(query_image=base64.b64encode(raw).decode())
        SearchRequest.model_validate(payload)
    body_bytes = len(json.dumps(payload).encode())
    assert body_bytes < 8*1024*1024
    observed['image_pixels'] = dict(accepted=True, dimensions=[12000, 12000],
        body_bytes=body_bytes, rgb_bytes_before_additional_copies=12000*12000*3,
        warnings=[str(w.message) for w in caught], allocation_scope='validation only; no RGB decode or live stress')

    from src.search.api import SearchTransport

    async def malformed_content_type():
        async def unused(*args):
            raise AssertionError('downstream app must not run')
        async def receive():
            return {'type': 'http.request', 'body': b'{}', 'more_body': False}
        await SearchTransport(unused)({'type': 'http', 'path': '/api/search', 'method': 'POST',
            'headers': [(b'content-type', b'\xff')]}, receive, unused)

    try:
        asyncio.run(malformed_content_type())
    except UnicodeDecodeError as error:
        observed['malformed_content_type'] = dict(unhandled=type(error).__name__)
    else:
        raise AssertionError('expected unhandled header decode error')
    return observed


def conversion_timing(root: Path, window_seconds: int) -> dict:
    events = pd.read_parquet(root / 'events.parquet', columns=[
        'user_id', 'product_id', 'session_id', 'event_type', 'timestamp'])
    keys = ['user_id', 'product_id', 'session_id']
    views = events[events.event_type == 'view'][keys+['timestamp']].rename(
        columns={'timestamp': 'view_at'}).sort_values('view_at')
    purchases = events[events.event_type == 'purchase'][keys+['timestamp']].sort_values('timestamp')
    linked = pd.merge_asof(purchases, views, left_on='timestamp', right_on='view_at',
                           by=keys, direction='backward', allow_exact_matches=False)
    gaps = (linked.timestamp-linked.view_at).dt.total_seconds().dropna()
    return dict(source=str(root / 'events.parquet'), purchases=len(purchases),
        purchases_with_preceding_same_session_view=len(gaps), attribution_window_seconds=window_seconds,
        minimum_view_to_purchase_seconds=float(gaps.min()) if len(gaps) else None,
        median_view_to_purchase_seconds=float(gaps.median()) if len(gaps) else None,
        within_window=int((gaps <= window_seconds).sum()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, help='optional existing dataset; read-only timing check')
    args = parser.parse_args()
    result = run()
    if args.data_dir:
        result['conversion_timing'] = conversion_timing(args.data_dir,
            load_config()['recommend']['ranking']['attribution_seconds'])
    print(json.dumps(result, ensure_ascii=False, indent=2))
