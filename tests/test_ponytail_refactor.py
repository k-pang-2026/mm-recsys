"""Regression cases from the whole-project Ponytail audit."""
import asyncio
import base64
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import fakeredis
import httpx
import numpy as np
import pandas as pd
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from src.common.config import load_config
from src.common.schemas import SearchRequest, UserFeatures
from src.ct import retrain_trigger
from src.ct.storage import Journal
from src.evaluation.reporting import quality_status
from src.recommendation.ranking_labels import build_labels
from src.recommendation.recommender import Recommender
from src.recommendation.reranking import diversity_capacity
from src.search.api import SearchTransport
from src.serving.feature_store import RedisFeatureStore
from src.serving.main import create_app


@pytest.mark.parametrize('size', [(4001,4000), (10000,1), (4096,1)])
def test_compressed_large_image_is_rejected_before_pixels_are_loaded(size):
    stream = BytesIO()
    with Image.new('L', size) as image:
        image.save(stream, format='PNG')
    assert len(stream.getvalue()) < 8*1024*1024
    with pytest.raises(ValueError, match='valid base64-encoded image'):
        SearchRequest(query_image=base64.b64encode(stream.getvalue()).decode())


def test_non_ascii_content_type_returns_validation_response():
    output = []
    async def receive():
        return {'type': 'http.request', 'body': b'{}', 'more_body': False}
    async def send(message):
        output.append(message)
    async def downstream(*args):
        pytest.fail('invalid header reached the model')
    asyncio.run(SearchTransport(downstream)({'type': 'http', 'path': '/api/search',
        'method': 'POST', 'headers': [(b'content-type', b'\xff')]}, receive, send))
    assert output[0]['status'] == 422


def test_storage_failure_retries_without_skipping_or_duplicating_events(monkeypatch):
    from docker import simulator
    cfg = load_config(); cfg['serving']['ct']['enabled'] = False
    backend = fakeredis.FakeRedis(decode_responses=True)
    store = RedisFeatureStore(backend)
    unavailable = Mock(); unavailable.pipeline.side_effect = RedisConnectionError('offline')
    rows = pd.DataFrame([dict(event_id='click', user_id='u', product_id='p', event_type='view', session_id='s')])
    with TestClient(create_app(cfg, search_service=object(), recommend_service=object(), feature_store=store)) as client:
        def request(url, payload):
            response = client.post('/api/'+url.rsplit('/', 1)[1], json=payload)
            response.raise_for_status()
            return response.json()
        monkeypatch.setattr(simulator, 'request', request)
        store.client = unavailable
        with pytest.raises(httpx.HTTPStatusError) as error:
            simulator.send_rows('http://unused', rows, {})
        assert error.value.response.status_code == 503
        assert client.post('/api/feedback', json=rows.iloc[0].to_dict()).status_code == 503
        store.client = backend
        simulator.send_rows('http://unused', rows, {})
        simulator.send_rows('http://unused', rows, {})
        assert store.get_features('u').recent_clicks == ['p']
        assert backend.hget(store.key('reward', 'p'), 'clicks') == '1'


def test_simulator_retries_both_http_and_checkpoint_failures_without_skipping(monkeypatch, tmp_path):
    import json
    from urllib.error import HTTPError
    from docker import simulator
    (tmp_path/'split_manifest.json').write_text(json.dumps({'generation_fingerprint': 'f'}))
    pd.DataFrame([dict(event_id='e1', user_id='u', product_id='p', event_type='view',
        session_id='s', timestamp=pd.Timestamp('2026-01-01'))]).to_parquet(tmp_path/'events.parquet')
    pd.DataFrame([dict(product_id='p', category_l1='a')]).to_parquet(tmp_path/'products.parquet')
    store = RedisFeatureStore(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(store.client, 'info', lambda *args: {'run_id': 'fixture'})
    monkeypatch.setattr('src.serving.feature_store.create_feature_store', lambda cfg: store)
    monkeypatch.setattr(simulator, 'runtime_config', lambda: {'paths': {'data_dir': str(tmp_path)}})
    monkeypatch.setattr(simulator, 'wait_ready', lambda *args: None)
    sent = []; checkpoints = []; original_set = store.client.set
    def send(api, rows, categories):
        sent.append(rows.event_id.tolist())
        if len(sent) == 1:
            raise HTTPError(api, 503, 'temporary storage outage', {}, None)
    def save(*args, **kwargs):
        if len(sent) == 2:
            raise RedisConnectionError('checkpoint temporarily unavailable')
        return original_set(*args, **kwargs)
    def sleep(seconds):
        raw = store.client.get(store.key('simulator_checkpoint', 'f'))
        checkpoints.append(json.loads(raw)['offset'] if raw else 0)
        if len(checkpoints) == 3:
            raise StopIteration
    monkeypatch.setattr(simulator, 'send_rows', send)
    monkeypatch.setattr(store.client, 'set', save)
    monkeypatch.setattr(simulator.time, 'sleep', sleep)
    with pytest.raises(StopIteration):
        simulator.main()
    assert sent == [['e1'], ['e1'], ['e1']] and checkpoints == [0,0,1]


def test_repeated_clicks_are_binary_ctr_and_purchase_uses_last_view(tmp_path):
    at = pd.Timestamp('2026-01-01', tz='UTC')
    journal = Journal(tmp_path / 'journal.sqlite3')
    journal.exposure('r', 'u', ['p'], 1, 'v1.0', at.timestamp())
    rows = []
    for identity, kind, seconds in [('view1', 'view', 1), ('view2', 'view', 1700), ('buy', 'purchase', 2000)]:
        assert journal.event(dict(event_id=identity, event_type=kind, user_id='u', product_id='p'),
                             at.timestamp()+seconds, 'r', 3600)
        rows.append(dict(event_id=identity, event_type=kind, user_id='u', product_id='p',
            session_id='s', timestamp=at+pd.Timedelta(seconds=seconds),
            impression_id='r:p' if kind == 'view' else None))
    impressions = pd.DataFrame([dict(impression_id='r:p', request_id='r', user_id='u',
        product_id='p', exposed_at=at, position=1)])
    labels, diagnostics = build_labels(impressions, pd.DataFrame(rows), at, at+pd.Timedelta(hours=1), 1800)
    assert len(labels) == 1 and labels.ctr.tolist() == labels.cvr.tolist() == [1]
    assert diagnostics['clicks'] == diagnostics['conversions'] == 1
    with pytest.raises(ValueError, match='duplicate'):
        build_labels(impressions, pd.DataFrame(rows+rows[:1]), at, at+pd.Timedelta(hours=1), 1800)


def test_watch_recovers_pending_reload_before_training(monkeypatch, tmp_path):
    cfg = load_config(); active = ['v1.0']; calls = []
    registry = SimpleNamespace(read=lambda: {'active': active[0]}, log=tmp_path/'ct.jsonl')
    monkeypatch.setattr('sys.argv', ['ct', '--watch', '--train', '--reload-url', 'http://127.0.0.1:8000'])
    monkeypatch.setattr(retrain_trigger, 'load_config', lambda: cfg)
    monkeypatch.setattr(retrain_trigger, 'components', lambda cfg: ({'poll_seconds': 1}, object(), registry))
    monkeypatch.setattr('src.ct.monitor.monitor', lambda *args: None)
    def train(*args):
        calls.append('train')
        if active[0] == 'v1.1':
            raise StopIteration('test finished after recovered reload')
        active[0] = 'v1.1'
        return dict(status='PROMOTED', active='v1.1')
    def reload(url, version):
        calls.append('reload:'+version)
        if calls.count('reload:v1.1') == 1:
            raise RuntimeError('temporary HTTP 503')
    monkeypatch.setattr(retrain_trigger, 'trigger', train)
    monkeypatch.setattr(retrain_trigger, 'reload_api', reload)
    monkeypatch.setattr(retrain_trigger.time, 'sleep', lambda seconds: calls.append('sleep'))
    with pytest.raises(StopIteration):
        retrain_trigger.main()
    assert calls == ['reload:v1.0', 'train', 'reload:v1.1', 'sleep', 'reload:v1.1', 'train']
    assert 'reload_retry' in registry.log.read_text()


def test_cold_pool_is_bounded_diverse_and_excludes_future_and_purchases():
    cfg = load_config()
    service = object.__new__(Recommender)
    service.cfg = cfg
    service.scoring = {'strategy': 'ctr'}
    service.at = pd.Timestamp(cfg['simulator']['reference_time'])
    service.fallback_sorted = [f'p{i}' for i in range(500)]
    mapping = {p: i for i, p in enumerate(service.fallback_sorted)}
    service.table = SimpleNamespace(id_to_index=mapping)
    service.candidate = SimpleNamespace(allowed=set(range(499)))
    service.reranker = SimpleNamespace(categories={p: 'a' if i < 400 else 'b' for p, i in mapping.items()})
    service.reranker.created = {p: service.at-pd.Timedelta(days=30) for p in mapping}
    service.catalog_by_recency = service.fallback_sorted
    cfg['recommend']['exclude_purchased'] = True
    context = SimpleNamespace(history_count=0, purchased=frozenset({400}))
    products = service.candidate_products(context, UserFeatures(), 50)
    assert len(products) == len(set(products)) == 300
    assert 'p400' not in products and 'p499' not in products
    from collections import Counter
    assert diversity_capacity(Counter(service.reranker.categories[p] for p in products), 2) >= 50


def test_quality_cannot_hide_an_infeasible_pool_or_missing_candidates():
    rows = [{'status': 'PASS'}]
    rec = dict(candidate={'ann_two_tower': {'candidate_count_min': 300}},
               feasible_constraint_violations=0, infeasible_candidate_pools=1)
    assert quality_status(rows, rec, 300) == 'FAIL'
    rec['infeasible_candidate_pools'] = 0
    assert quality_status(rows, rec, 300) == 'PASS'
    rec['candidate']['ann_two_tower']['candidate_count_min'] = 299
    assert quality_status(rows, rec, 300) == 'FAIL'
    rec['candidate']['ann_two_tower'].pop('candidate_count_min')
    assert quality_status(rows, rec, 300) == 'UNMEASURED'


@pytest.mark.parametrize('split', ['train', 'valid'])
def test_training_rejects_single_class_cvr_before_writing_models(monkeypatch, split):
    from src.recommendation import train_deepfm
    labels = {name: pd.DataFrame({'cvr': [0,1], 'cvr_mask': [True,True]}) for name in ('train','valid')}
    labels[split]['cvr'] = 0
    monkeypatch.setattr(train_deepfm, 'prepare', lambda cfg: ({}, labels, {}))
    with pytest.raises(ValueError, match=split+' CVR requires'):
        train_deepfm.train(load_config())


def test_generator_has_observed_conversions_and_distributed_cold_arrivals():
    from src.simulator.catalog import make_catalog
    from src.simulator.users import make_users
    from src.simulator.events import make_events
    from src.simulator.split import chronological_split
    cfg = load_config(); cfg['simulator'].update(n_products=450, n_users=120, n_events=12000, cold_user_ratio=.2)
    rng = np.random.default_rng(42)
    products = make_catalog(cfg, rng); users = make_users(cfg, rng)
    events, impressions = make_events(cfg, products, users, rng)
    assert events.timestamp.is_monotonic_increasing
    assert events.timestamp.max() < pd.Timestamp(cfg['simulator']['reference_time'])
    sizes = events.groupby('user_id').size()
    cold = set(sizes[sizes <= cfg['simulator']['cold_max_events']].index)
    parts = chronological_split(events, cfg['split'])
    assert set(parts['test'].user_id) & cold
    for name in ('train', 'valid'):
        part = parts[name]
        labels, diagnostics = build_labels(impressions, events, part.timestamp.min(), part.timestamp.max(), 1800)
        assert diagnostics['conversions'] > 0
        assert 0 < labels.cvr.sum() < labels.cvr_mask.sum()
    linked = events[events.product_id.notna()].merge(products[['product_id', 'created_at']], on='product_id')
    assert (linked.timestamp >= linked.created_at).all()


def test_session_batching_keeps_same_timestamp_views_out_of_each_others_history():
    from src.recommendation.train_session import examples
    at = pd.Timestamp('2026-01-01', tz='UTC')
    events = pd.DataFrame([dict(event_id=str(i), user_id='u', session_id='s', event_type='view',
        product_id=f'p{i}', timestamp=at+pd.Timedelta(minutes=i//2)) for i in range(5)])
    table = SimpleNamespace(id_to_index={f'p{i}': i+1 for i in range(5)},
                            created=np.zeros(6, dtype=np.int64))
    sequences, targets, times, latest = examples(events, table, 5, at, at+pd.Timedelta(minutes=3))
    assert targets.tolist() == [3,4,5]
    assert sequences.tolist() == [[1,2,0,0,0],[1,2,0,0,0],[1,2,3,4,0]]
    assert (latest < times).all()


def test_vectorized_training_fetch_preserves_batches_and_shuffle_state(tmp_path):
    import torch
    from torch.utils.data import BatchSampler, DataLoader, RandomSampler
    from src.recommendation.testing import service_fixture
    from src.recommendation.datasets import TrainingDataset, cutoff_for
    from src.recommendation.features import FeatureEncoder
    cfg, data = service_fixture(tmp_path)
    encoder = FeatureEncoder.fit(data['products'], data['users'], cutoff_for(data, 'valid'))
    dataset = TrainingDataset(data['train'], data['users'], encoder, encoder.item_table(data['products']), cfg)
    left = torch.Generator().manual_seed(44); right = torch.Generator().manual_seed(44)
    old = DataLoader(dataset, batch_size=4, shuffle=True, generator=left)
    new = DataLoader(dataset, batch_size=None,
        sampler=BatchSampler(RandomSampler(dataset, generator=right), 4, drop_last=False), generator=right)
    for _ in range(3):
        old_batches, new_batches = list(old), list(new)
        assert len(old_batches) == len(new_batches)
        assert all(torch.equal(a[key], b[key]) for a, b in zip(old_batches, new_batches) for key in a)
        assert torch.equal(left.get_state(), right.get_state())
