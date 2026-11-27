"""Sliding window rate limiter. In process. Use a shared store such as Redis when you run more than one API instance."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from packages.contracts.errors import DomainError, ErrorCode


class SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._hits[key]
        cutoff = self._clock() - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def allow(self, key: str, *, record: bool = True) -> bool:
        q = self._prune(key)
        if len(q) >= self.limit:
            return False
        if record:
            q.append(self._clock())
        return True

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.limit

    def reset(self) -> None:
        self._hits.clear()


_LIMITERS: dict[str, SlidingWindowLimiter] = {}


def limiter(name: str, limit: int) -> SlidingWindowLimiter:
    existing = _LIMITERS.get(name)
    if existing is None or existing.limit != limit:
        existing = SlidingWindowLimiter(limit=limit)
        _LIMITERS[name] = existing
    return existing


def enforce(name: str, key: str, limit: int) -> None:
    if not limiter(name, limit).allow(key):
        raise DomainError(ErrorCode.RATE_LIMITED, f"Rate limit reached for '{name}'. Try again in a minute.", status_code=429)


def reset_limiters() -> None:
    _LIMITERS.clear()
