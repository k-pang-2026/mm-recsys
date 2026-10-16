"""Atomic Redis attribution shared across workers, not an in-memory simulation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import os
import time
import uuid

import fakeredis
import pytest
import redis

from src.common.config import load_config
from src.common.schemas import FeedbackRequest
from src.serving.feature_store import RedisFeatureStore


@pytest.fixture(params=['fake', 'redis'])
def stores(request):
    if request.param == 'redis' and os.getenv('RUN_REDIS_TESTS') != '1':
        pytest.skip('requires explicit real Redis test environment')
    client = (fakeredis.FakeRedis(decode_responses=True) if request.param == 'fake'
              else redis.Redis(host=os.getenv('REDIS_HOST', 'localhost'),
                               port=int(os.getenv('REDIS_PORT', '6379')), decode_responses=True))
    client.ping()
    namespace = 'mm-recsys:test-mab:' + uuid.uuid4().hex
    spec = copy.deepcopy(load_config()['recommend']['mab'])
    a, b = [RedisFeatureStore(client, namespace=namespace, mab_spec=spec, write_retries=64) for _ in range(2)]
    try:
        yield a, b
    finally:
        keys = list(client.scan_iter(match=namespace + ':*'))
        if keys:
            client.delete(*keys)
        client.close()


def feedback(identifier, kind='view', user='u', product='p'):
    return FeedbackRequest(event_id=identifier, user_id=user, product_id=product, event_type=kind)


def test_cross_worker_latest_exposure_and_reward_cap(stores):
    a, b = stores
    assert len(a.record_exposures('u', ['p', 'p', 'other'])) == 2
    assert b.update_reward(feedback('click'))
    assert b.update_reward(feedback('buy', 'purchase'))
    assert not a.update_reward(feedback('buy', 'purchase'))
    assert a.update_reward(feedback('later-click'))
    assert a.arm_statistics(['p'])['p'] == dict(exposures=1, reward=1.0)
    b.record_exposures('u', ['p'])
    a.update_reward(feedback('new-click'))
    assert b.arm_statistics(['p'])['p'] == dict(exposures=2, reward=1.2)
    assert set(b.arm_statistics(['p'])) == {'p'}
    assert set(b.arm_statistics()) == {'p', 'other'}


def test_feedback_cannot_cross_users_or_extend_attribution(stores):
    a, b = stores
    a.record_exposures('u', ['p'])
    assert b.update_reward(feedback('unknown-user', 'purchase', user='other-user'))
    assert b.unattributed_feedback == 1
    keys = list(a.client.scan_iter(match=a.namespace + ':exposure:*'))
    assert len(keys) == 1
    a.client.pexpire(keys[0], 80)
    b.update_reward(feedback('click'))
    assert 0 < a.client.pttl(keys[0]) <= 80
    time.sleep(0.10)
    b.update_reward(feedback('expired', 'purchase'))
    assert a.unattributed_feedback == 2
    assert a.arm_statistics()['p']['reward'] == 0.2


def test_concurrent_feedback_cannot_double_reward(stores):
    a, b = stores
    a.record_exposures('u', ['p'])
    def apply(index):
        store = a if index % 2 else b
        return store.update_reward(feedback(f'event-{index}', 'view' if index % 2 else 'purchase'))
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(apply, range(32)))
    assert a.arm_statistics()['p'] == dict(exposures=1, reward=1.0)


def test_category_arms_and_statistics_snapshot_are_shared(stores):
    a, b = stores
    for store in (a, b):
        store.mab_spec['arm'] = 'category'
        store.configure_categories({'p': 'shirts:plain', 'other': 'shirts:plain'})
    a.record_exposures('u', ['p', 'other'])
    b.update_reward(feedback('purchase', 'purchase', product='other'))
    stats = a.arm_statistics(['p'])
    assert stats == {'shirts:plain': dict(exposures=2, reward=1.0)}
    stats['shirts:plain']['reward'] = 999
    assert b.arm_statistics(['p'])['shirts:plain']['reward'] == 1.0


def test_ab_users_share_only_immutable_catalog_metadata():
    import pandas as pd
    from src.evaluation.ab_test import UserIsolatedStore
    cfg = load_config()
    field = cfg['recommend']['reranking']['category_field']
    products = pd.DataFrame({'product_id': ['p'], field: ['shirts']})
    store = UserIsolatedStore(cfg, products, lambda: 0.)
    first, second = store.user_store('u'), store.user_store('other')
    assert first.categories is second.categories
    with pytest.raises(TypeError):
        first.categories['p'] = 'changed'
    first.record_exposures('u', ['p'])
    first.update_reward(feedback('purchase', 'purchase'))
    assert first.arm_statistics()['p']['reward'] == 1.0
    assert second.arm_statistics() == {}
