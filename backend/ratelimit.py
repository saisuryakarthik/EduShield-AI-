"""
In-process, dependency-free rate limiting.

This is a fixed-window counter keyed by an arbitrary string (usually
"bucket:identity"). It is intentionally simple:

    * No external services (no Redis, no extra packages).
    * Thread-safe (a single lock guards the hit store).
    * Bounded: old buckets are pruned so the store cannot grow forever.

LIMITATION: state lives in one process. Behind a multi-worker WSGI
server (e.g. gunicorn -w 4) each worker counts separately, so the
effective limit is roughly (workers x limit). For a shared, exact limit
use a backing store such as Redis. This module is a safe default, not a
distributed solution.
"""

import threading
import time


class RateLimiter:
    def __init__(self, max_keys=10000):
        self._hits = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys
        self._last_prune = time.time()

    def allow(self, key, limit, window_seconds):
        """
        Record an attempt for `key`.

        Returns (allowed: bool, retry_after_seconds: int).
        """

        now = time.time()
        window = float(window_seconds)

        with self._lock:
            self._prune_locked(now)

            hits = [
                t for t in self._hits.get(key, ())
                if now - t < window
            ]

            if len(hits) >= limit:
                self._hits[key] = hits
                retry_after = int(window - (now - hits[0])) + 1
                return False, max(retry_after, 1)

            hits.append(now)
            self._hits[key] = hits

            return True, 0

    def reset(self, key=None):
        """Clear one key, or every key when `key` is None."""

        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def _prune_locked(self, now):
        # Time-based prune at most once per minute, or when the store
        # grows past the cap.
        if (
            now - self._last_prune < 60
            and len(self._hits) < self._max_keys
        ):
            return

        self._last_prune = now

        stale = [
            k for k, hits in self._hits.items()
            if not hits or now - hits[-1] > 3600
        ]

        for k in stale:
            self._hits.pop(k, None)


# One shared limiter for the application.
limiter = RateLimiter()
