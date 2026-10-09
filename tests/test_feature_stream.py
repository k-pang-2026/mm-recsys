import json

import fakeredis
import pandas as pd
import pytest

from src.serving.feature_store import RedisFeatureStore
from src.serving.stream_features import replay_stream


def test_stream_replay_is_idempotent_and_changed_chunks_are_rejected(tmp_path):
    pd.DataFrame([{"product_id": "p", "category_l1": "tops"}]).to_parquet(tmp_path / "products.parquet")
    (tmp_path / "split_manifest.json").write_text(json.dumps({"generation_fingerprint": "v1"}))
    stream = tmp_path / "stream"
    stream.mkdir()
    chunk = stream / "events-000000000.parquet"
    rows = [{"event_id": "e", "user_id": "u", "product_id": "p",
             "session_id": "s", "event_type": "view"},
            {"event_id": "search", "user_id": "u", "product_id": None,
             "session_id": "s", "event_type": "search"}]
    pd.DataFrame(rows).to_parquet(chunk)
    cfg = {"paths": {"data_dir": str(tmp_path)}}
    store = RedisFeatureStore(fakeredis.FakeRedis(decode_responses=True))
    assert replay_stream(cfg, store)["events_processed"] == 1
    assert replay_stream(cfg, store)["events_processed"] == 0
    assert store.get_features("u").recent_clicks == ["p"]
    assert store.client.hget(store.key("reward", "p"), "clicks") == "1"
    rows[0]["product_id"] = "changed"
    pd.DataFrame(rows).to_parquet(chunk)
    with pytest.raises(ValueError, match="changed"):
        replay_stream(cfg, store)


def test_failed_replay_does_not_advance_checkpoint(tmp_path):
    from unittest.mock import Mock
    from redis.exceptions import ConnectionError as RedisConnectionError
    pd.DataFrame([{"product_id": "p", "category_l1": "tops"}]).to_parquet(tmp_path / "products.parquet")
    (tmp_path / "split_manifest.json").write_text(json.dumps({"generation_fingerprint": "v1"}))
    stream = tmp_path / "stream"
    stream.mkdir()
    pd.DataFrame([{"event_id": "e", "user_id": "u", "product_id": "p",
                   "session_id": "s", "event_type": "view"}]).to_parquet(stream / "events-0.parquet")
    client = Mock()
    client.pipeline.side_effect = RedisConnectionError("offline")
    store = RedisFeatureStore(client)
    with pytest.raises(ConnectionError, match="checkpoint"):
        replay_stream({"paths": {"data_dir": str(tmp_path)}}, store)
    assert not list(stream.glob("*.json"))
