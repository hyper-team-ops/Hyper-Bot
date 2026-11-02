"""Small in-memory per-user sliding-window limiter."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._last_cleanup = time.monotonic()

    @staticmethod
    def _discard_expired(events: deque[float], threshold: float) -> None:
        while events and events[0] <= threshold:
            events.popleft()

    def _cleanup(self, now: float, threshold: float) -> None:
        if now - self._last_cleanup < self.window_seconds:
            return
        for user_id, events in list(self._events.items()):
            self._discard_expired(events, threshold)
            if not events:
                self._events.pop(user_id, None)
        self._last_cleanup = now

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        threshold = now - self.window_seconds
        self._cleanup(now, threshold)
        events = self._events[user_id]
        self._discard_expired(events, threshold)
        if len(events) >= self.requests:
            return False
        events.append(now)
        return True
