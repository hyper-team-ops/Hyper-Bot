"""Small in-memory per-user sliding-window limiter."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        threshold = now - self.window_seconds
        events = self._events[user_id]
        while events and events[0] <= threshold:
            events.popleft()
        if len(events) >= self.requests:
            return False
        events.append(now)
        return True
