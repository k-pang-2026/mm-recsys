"""Opt-in real Redis checks; all writes use an isolated, disposable namespace."""
import os
import time
import uuid

import pytest
import redis

from src.common.schemas import EventRequest, FeedbackRequest
from src.serving.feature_store import RedisFeatureStore

pytestmark = pytest.mark.skipif(os.getenv("RUN_REDIS_TESTS") != "1",
                                reason="set RUN_REDIS_TESTS=1 with a local Redis server")


@pytest.fixture
def store():
    client = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"),
                         port=int(os.getenv("REDIS_PORT", "6379")),
                         decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
    client.ping()
    namespace = "mm-recsys:integration:" + uuid.uuid4().hex
    instance = RedisFeatureStore(client, namespace=namespace, history_limit=2)
    try:
        yield instance
    finally:
        keys = list(client.scan_iter(match=namespace + ":*"))
        if keys:
            client.delete(*keys)
        client.close()


def test_real_redis_session_expiry_and_atomic_deduplication(store):
    store.batch_load_profiles({"u": {"age_group": "18-24", "count": 3}})
    payload = EventRequest(event_id="e", user_id="u", product_id="p", event_type="view",
                           category="tops", session_id="s")
    assert store.append_event(payload)
    assert not store.append_event(payload)
    assert store.get_features("u").session_clicks == 1
    store.client.pexpire(store.key("user", "u", "session"), 1)
    store.client.pexpire(store.key("user", "u", "recent_views"), 1)
    deadline = time.monotonic() + 1
    while store.client.exists(store.key("user", "u", "session")) and time.monotonic() < deadline:
        time.sleep(0.005)
    features = store.get_features("u")
    assert features.session_clicks == 0 and features.recent_clicks == []
    assert features.profile == {"age_group": "18-24", "count": 3}
    feedback = FeedbackRequest(**payload.model_dump())
    assert store.update_reward(feedback) and not store.update_reward(feedback)
    assert store.client.hget(store.key("reward", "p"), "clicks") == "1"
