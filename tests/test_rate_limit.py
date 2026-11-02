import unittest
from unittest.mock import patch

from bot.services.rate_limit import RateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_limit_and_window_reset(self):
        limiter = RateLimiter(requests=2, window_seconds=10)
        with patch("bot.services.rate_limit.time.monotonic", return_value=100):
            self.assertTrue(limiter.allow(1))
            self.assertTrue(limiter.allow(1))
            self.assertFalse(limiter.allow(1))
        with patch("bot.services.rate_limit.time.monotonic", return_value=111):
            self.assertTrue(limiter.allow(1))

    def test_expired_user_buckets_are_removed(self):
        limiter = RateLimiter(requests=1, window_seconds=10)
        limiter._last_cleanup = 0
        with patch("bot.services.rate_limit.time.monotonic", return_value=1):
            limiter.allow(1)
        with patch("bot.services.rate_limit.time.monotonic", return_value=20):
            limiter.allow(2)
        self.assertNotIn(1, limiter._events)
