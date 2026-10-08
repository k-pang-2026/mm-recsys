"""Functional shared backend; lane C replaces storage with Redis without changing callers."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from src.common.schemas import EventRequest, FeedbackRequest, UserFeatures


class MemoryFeatureStore:
    def __init__(self, history_limit: int = 50, session_ttl: int = 1800,
                 feedback_ttl: int = 86400, clock: Callable[[], float] = time.monotonic) -> None:
        self.history_limit = history_limit
        self.session_ttl, self.feedback_ttl = session_ttl, feedback_ttl
        self.clock = clock
        self._lock = threading.RLock()
        self._profiles: dict[str, dict] = {}
        self._sessions: dict[str, tuple[str, float, deque, int, str | None]] = {}
        self._seen: dict[tuple[str, str], float] = {}
        self.rewards: dict[str, dict[str, int]] = defaultdict(lambda: {'clicks': 0, 'purchases': 0})

    def _expire(self, now: float) -> None:
        self._seen = {key: expires for key, expires in self._seen.items() if expires > now}

    def get_features(self, user_id: str) -> UserFeatures:
        with self._lock:
            value = self._sessions.get(user_id)
            if value and self.clock() - value[1] >= self.session_ttl:
                self._sessions.pop(user_id)
                value = None
            return UserFeatures(recent_clicks=list(value[2]) if value else [],
                                session_clicks=value[3] if value else 0,
                                session_interest=value[4] if value else None,
                                profile=dict(self._profiles.get(user_id, {})))

    def append_event(self, event: EventRequest) -> bool:
        with self._lock:
            now = self.clock()
            self._expire(now)
            key = ('event', event.event_id)
            if key in self._seen:
                return False
            self._seen[key] = now + self.feedback_ttl
            old = self._sessions.get(event.user_id)
            if not old or old[0] != event.session_id or now - old[1] >= self.session_ttl:
                old = (event.session_id, now, deque(maxlen=self.history_limit), 0, None)
            clicks = old[2]
            if event.event_type == 'view':
                clicks.append(event.product_id)
            self._sessions[event.user_id] = (event.session_id, now, clicks,
                                             old[3] + int(event.event_type == 'view'), event.category or old[4])
            return True

    def update_reward(self, feedback: FeedbackRequest) -> bool:
        with self._lock:
            now = self.clock()
            self._expire(now)
            key = ('feedback', feedback.event_id)
            if key in self._seen:
                return False
            self._seen[key] = now + self.feedback_ttl
            if feedback.event_type == 'view':
                self.rewards[feedback.product_id]['clicks'] += 1
            elif feedback.event_type == 'purchase':
                self.rewards[feedback.product_id]['purchases'] += 1
            return True

    def batch_load_profiles(self, profiles: dict[str, dict]) -> None:
        with self._lock:
            self._profiles.update({key: dict(value) for key, value in profiles.items()})
