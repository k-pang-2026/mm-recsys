"""Pytest plugin: isolate implicit API stores while retaining the real Redis backend."""
from __future__ import annotations

import copy
import uuid
from collections.abc import Iterator

import pytest
from redis.exceptions import RedisError

from src.serving import main
from src.serving.feature_store import RedisFeatureStore, create_feature_store
from src.serving.memory_store import MemoryFeatureStore


@pytest.fixture(autouse=True)
def isolate_default_api_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    namespace = "mm-recsys:test-api:" + uuid.uuid4().hex
    stores: list[RedisFeatureStore | MemoryFeatureStore] = []

    def factory(cfg: dict) -> RedisFeatureStore | MemoryFeatureStore:
        isolated = copy.deepcopy(cfg)
        isolated["serving"].setdefault("redis", {})["namespace"] = namespace
        store = create_feature_store(isolated)
        stores.append(store)
        return store

    monkeypatch.setattr(main, "create_feature_store", factory)
    try:
        yield
    finally:
        for store in stores:
            if isinstance(store, RedisFeatureStore):
                try:
                    keys = list(store.client.scan_iter(match=namespace + ":*"))
                    if keys:
                        store.client.delete(*keys)
                except RedisError:
                    # An outage test can intentionally leave the connection unavailable.
                    pass
                finally:
                    store.close()

