"""Redis implementation of the shared FeatureStore contract."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from typing import Any, cast

import redis
from redis.exceptions import RedisError, WatchError

from src.common.schemas import EventRequest, FeedbackRequest, UserFeatures
from src.serving.memory_store import MemoryFeatureStore

LOG = logging.getLogger(__name__)


class RedisFeatureStore:
    def __init__(self, client: Any = None, *, host: str = "localhost", port: int = 6379,
                 db: int = 0, namespace: str = "mm-recsys:dev", history_limit: int = 50,
                 session_ttl: int = 1800, feedback_ttl: int = 86400,
                 timeout: float = 0.2, max_connections: int = 32,
                 write_retries: int = 8) -> None:
        if min(history_limit, session_ttl, feedback_ttl, write_retries, max_connections) < 1:
            raise ValueError("limits, TTLs and retry counts must be positive")
        if timeout <= 0 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", namespace):
            raise ValueError("timeout must be positive and namespace must contain safe key characters")
        self.history_limit = history_limit
        self.session_ttl = session_ttl
        self.feedback_ttl = feedback_ttl
        self.namespace = namespace
        self.write_retries = write_retries
        self._owned_client = client is None
        self.client = client if client is not None else redis.Redis(
            connection_pool=redis.ConnectionPool(
                host=host, port=port, db=db, decode_responses=True,
                socket_connect_timeout=timeout, socket_timeout=timeout,
                max_connections=max_connections))
        self.available = True

    def key(self, kind: str, identity: str, suffix: str = "") -> str:
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"{self.namespace}:{kind}:{digest}" + (f":{suffix}" if suffix else "")

    def _failure(self, operation: str, error: Exception) -> None:
        self.available = False
        LOG.warning("Redis %s unavailable; using empty features: %s", operation, error)

    def get_features(self, user_id: str) -> UserFeatures:
        try:
            # MULTI/EXEC gives a consistent snapshot in a single network round-trip.
            with self.client.pipeline(transaction=True) as pipe:
                pipe.lrange(self.key("user", user_id, "recent_views"), 0, -1)
                pipe.hgetall(self.key("user", user_id, "session"))
                pipe.hgetall(self.key("user", user_id, "profile"))
                views, session, profile = pipe.execute()
            self.available = True
            return UserFeatures(
                recent_clicks=views if session else [],
                session_clicks=int(session.get("clicks", 0)),
                session_interest=session.get("interest"),
                profile={name: json.loads(value) for name, value in profile.items()})
        except (RedisError, ValueError, TypeError) as error:
            self._failure("get_features", error)
            return UserFeatures()

    def append_event(self, event: EventRequest) -> bool:
        session_key = self.key("user", event.user_id, "session")
        views_key = self.key("user", event.user_id, "recent_views")
        seen_key = self.key("event", event.event_id)
        try:
            for _ in range(self.write_retries):
                with self.client.pipeline() as pipe:
                    try:
                        pipe.watch(session_key, views_key, seen_key)
                        if pipe.exists(seen_key):
                            self.available = True
                            return False
                        old = cast(dict[str, str], pipe.hgetall(session_key))
                        reset = not old or old.get("id") != event.session_id
                        clicks = 0 if reset else int(old.get("clicks", 0))
                        interest = event.category or (None if reset else old.get("interest"))
                        values = {"id": event.session_id,
                                  "clicks": str(clicks + int(event.event_type == "view"))}
                        if interest is not None:
                            values["interest"] = interest
                        pipe.multi()
                        pipe.set(seen_key, "1", ex=self.feedback_ttl)
                        if reset:
                            pipe.delete(session_key, views_key)
                        pipe.hset(session_key, mapping=values)
                        if event.event_type == "view":
                            pipe.rpush(views_key, event.product_id)
                            pipe.ltrim(views_key, -self.history_limit, -1)
                        pipe.expire(session_key, self.session_ttl)
                        pipe.expire(views_key, self.session_ttl)
                        pipe.execute()
                        self.available = True
                        return True
                    except WatchError:
                        continue
            raise RedisError("event write contention exceeded configured retry limit")
        except RedisError as error:
            self._failure("append_event", error)
            return False

    def update_reward(self, feedback: FeedbackRequest) -> bool:
        seen_key = self.key("feedback", feedback.event_id)
        reward_key = self.key("reward", feedback.product_id)
        field = {"view": "clicks", "purchase": "purchases"}.get(feedback.event_type)
        try:
            for _ in range(self.write_retries):
                with self.client.pipeline() as pipe:
                    try:
                        pipe.watch(seen_key)
                        if pipe.exists(seen_key):
                            self.available = True
                            return False
                        pipe.multi()
                        pipe.set(seen_key, "1", ex=self.feedback_ttl)
                        if field:
                            pipe.hincrby(reward_key, field, 1)
                        pipe.execute()
                        self.available = True
                        return True
                    except WatchError:
                        continue
            raise RedisError("reward write contention exceeded configured retry limit")
        except RedisError as error:
            self._failure("update_reward", error)
            return False

    def batch_load_profiles(self, profiles: Mapping[str, dict], batch_size: int = 1000) -> None:
        if not 1 <= batch_size <= 1000:
            raise ValueError("profile batch_size must be 1..1000")
        # Validate before writing so malformed input never leaves a partial batch.
        encoded = [(user_id, {key: json.dumps(value, ensure_ascii=False, allow_nan=False)
                            for key, value in UserFeatures(profile=profile).profile.items()})
                   for user_id, profile in profiles.items()]
        try:
            for offset in range(0, len(encoded), batch_size):
                with self.client.pipeline(transaction=True) as pipe:
                    for user_id, profile in encoded[offset:offset + batch_size]:
                        key = self.key("user", user_id, "profile")
                        pipe.delete(key)
                        if profile:
                            pipe.hset(key, mapping=profile)
                    pipe.execute()
            self.available = True
        except RedisError as error:
            self._failure("batch_load_profiles", error)
            raise

    def close(self) -> None:
        if self._owned_client:
            self.client.close()
            self.client.connection_pool.disconnect()


def create_feature_store(cfg: dict) -> MemoryFeatureStore | RedisFeatureStore:
    settings = cfg["serving"]
    common = dict(history_limit=settings["history_limit"],
                  session_ttl=settings["session_ttl_seconds"],
                  feedback_ttl=settings["feedback_ttl_seconds"])
    backend = settings["feature_store"]
    if backend == "memory":
        return MemoryFeatureStore(**common)
    if backend != "redis":
        raise ValueError(f"unknown feature store backend: {backend}")
    options = settings.get("redis", {})
    return RedisFeatureStore(
        host=cfg["redis"]["host"], port=cfg["redis"]["port"], **common,
        db=options.get("db", 0),
        namespace=options.get("namespace", f"mm-recsys:{cfg['scale']}"),
        timeout=options.get("timeout_seconds", 0.2),
        max_connections=options.get("max_connections", 32),
        write_retries=options.get("write_retries", 8))
