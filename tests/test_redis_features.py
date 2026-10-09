from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import fakeredis
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from src.common.config import load_config
from src.common.schemas import EventRequest, FeedbackRequest, RecommendResponse
from src.serving.feature_store import RedisFeatureStore
from src.serving.main import create_app


def event(identity, *, user="u", product=None, session="s", kind="view", category=None):
    return EventRequest(event_id=identity, user_id=user, product_id=product or identity,
                        session_id=session, event_type=kind, category=category)


@pytest.fixture
def store():
    return RedisFeatureStore(fakeredis.FakeRedis(decode_responses=True),
                             history_limit=2, session_ttl=10, feedback_ttl=20)


def test_profiles_history_cap_session_switch_and_duplicate(store):
    store.batch_load_profiles({"u": {"age_group": "25-34", "score": 1.5, "visits": 2}})
    for i in range(3):
        assert store.append_event(event(str(i), category="tops"))
    assert not store.append_event(event("2", session="another"))
    features = store.get_features("u")
    assert features.recent_clicks == ["1", "2"]
    assert features.session_clicks == 3
    assert features.session_interest == "tops"
    assert features.profile["score"] == 1.5
    features.profile["score"] = 99
    assert store.get_features("u").profile["score"] == 1.5
    assert store.append_event(event("cart", session="new", kind="cart"))
    reset = store.get_features("u")
    assert reset.recent_clicks == [] and reset.session_clicks == 0
    assert reset.session_interest is None


def test_session_expiration_and_profile_survival(store):
    store.batch_load_profiles({"u": {"age_group": "25-34"}})
    store.append_event(event("e", category="tops"))
    # Use an explicit past deadline: fakeredis's same-tick expire(0) is racy on Windows.
    store.client.expireat(store.key("user", "u", "session"), 1)
    store.client.expireat(store.key("user", "u", "recent_views"), 1)
    assert store.get_features("u").session_clicks == 0
    assert store.get_features("u").profile == {"age_group": "25-34"}
    assert store.append_event(event("next", session="s"))
    assert store.get_features("u").recent_clicks == ["next"]


def test_sliding_ttls_and_dedup_ttl_are_consistent(store):
    store.append_event(event("e"))
    assert 0 < store.client.ttl(store.key("user", "u", "session")) <= 10
    assert 0 < store.client.ttl(store.key("user", "u", "recent_views")) <= 10
    assert 0 < store.client.ttl(store.key("event", "e")) <= 20
    store.append_event(event("cart", kind="cart"))
    assert store.get_features("u").session_clicks == 1


def test_rewards_are_atomic_idempotent_and_separate_from_events(store):
    payload = FeedbackRequest(**event("e", product="p", kind="purchase").model_dump())
    assert store.append_event(payload)
    assert store.update_reward(payload)
    assert not store.update_reward(payload)
    assert store.client.hget(store.key("reward", "p"), "purchases") == "1"
    with ThreadPoolExecutor(max_workers=4) as pool:
        applied = list(pool.map(lambda _: store.append_event(event("same")), range(4)))
    assert sum(applied) == 1


def test_get_uses_one_pipeline_execute(store):
    store.append_event(event("e"))
    pipeline = store.client.pipeline
    calls = []
    def tracked(*args, **kwargs):
        pipe = pipeline(*args, **kwargs)
        execute = pipe.execute
        def once():
            calls.append(True)
            return execute()
        pipe.execute = once
        return pipe
    store.client.pipeline = tracked
    assert store.get_features("u").session_clicks == 1
    assert len(calls) == 1


def test_batch_profiles_are_chunked_and_replacements_remove_old_fields(store):
    store.batch_load_profiles({str(i): {"gender": "x"} for i in range(1001)})
    assert store.get_features("1000").profile == {"gender": "x"}
    store.batch_load_profiles({"1000": {"age_group": "18-24"}})
    assert store.get_features("1000").profile == {"age_group": "18-24"}
    with pytest.raises(ValueError):
        store.batch_load_profiles({}, batch_size=1001)


def test_failure_returns_empty_features_and_warning_and_recovers(store, caplog):
    original = store.client
    store.client = Mock()
    store.client.pipeline.side_effect = ConnectionError("offline")
    assert store.get_features("u").model_dump() == {
        "recent_clicks": [], "session_clicks": 0, "session_interest": None, "profile": {}}
    assert not store.append_event(event("e"))
    assert not store.update_reward(FeedbackRequest(**event("e").model_dump()))
    assert "using empty features" in caplog.text
    store.client = original
    assert store.append_event(event("recovered"))
    assert store.available


def test_recommendation_with_supplied_service_remains_200_when_redis_is_down(caplog):
    client = Mock()
    client.pipeline.side_effect = ConnectionError("offline")
    store = RedisFeatureStore(client)
    class ColdStartService:
        def recommend(self, user_id, top_n):
            features = store.get_features(user_id)
            return RecommendResponse(user_id=user_id, recommendations=[],
                                     pipeline_latency={}, session_context={
                                         "recent_clicks": features.recent_clicks,
                                         "session_interest": features.session_interest})
    with TestClient(create_app(load_config(), recommend_service=ColdStartService(),
                               feature_store=store)) as api:
        response = api.get("/api/recommend", params={"user_id": "unknown"})
        assert response.status_code == 200
        assert response.json()["session_context"]["recent_clicks"] == []
    assert "offline" in caplog.text


def test_factory_uses_configured_connection_pool():
    from src.serving.feature_store import create_feature_store
    cfg = load_config()
    store = create_feature_store(cfg)
    assert isinstance(store, RedisFeatureStore)
    assert store.client.connection_pool.connection_kwargs["host"] == cfg["redis"]["host"]
    assert store.client.connection_pool.max_connections == 32
    store.close()

