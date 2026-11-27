"""External API resilience: retry with backoff and a circuit breaker per dependency."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


class TransientIntegrationError(Exception):
    """A failure that can succeed on retry, such as a timeout or a 503."""


class PermanentIntegrationError(Exception):
    """A failure that retry cannot fix, such as a rejected request."""


class CircuitOpenError(Exception):
    """The breaker is open. The call was not sent."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.1
    max_delay_s: float = 2.0

    def delay(self, attempt: int) -> float:
        return float(min(self.max_delay_s, self.base_delay_s * (2 ** (attempt - 1))))


class CircuitBreaker:
    """closed -> open after N failures in a row -> half-open after the reset time -> closed on one success."""

    def __init__(self, name: str, *, failure_threshold: int = 3, reset_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self._clock() - self._opened_at >= self.reset_seconds else "open"

    def before_call(self) -> None:
        if self.state == "open":
            raise CircuitOpenError(f"Circuit '{self.name}' is open")

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold or self.state == "half_open":
            self._opened_at = self._clock()

    def snapshot(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state, "consecutive_failures": self._failures}


_BREAKERS: dict[str, CircuitBreaker] = {}


def breaker_for(name: str) -> CircuitBreaker:
    if name not in _BREAKERS:
        _BREAKERS[name] = CircuitBreaker(name)
    return _BREAKERS[name]


def breaker_snapshots() -> list[dict[str, Any]]:
    return [b.snapshot() for b in _BREAKERS.values()]


def reset_breakers() -> None:
    _BREAKERS.clear()


def call_with_resilience(
    fn: Callable[[], T],
    *,
    breaker: CircuitBreaker,
    policy: RetryPolicy = RetryPolicy(),
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Run fn. Retry transient errors with backoff. Return (result, attempts). Permanent errors do not retry."""
    attempt = 0
    while True:
        breaker.before_call()
        attempt += 1
        try:
            result = fn()
        except TransientIntegrationError:
            breaker.record_failure()
            if attempt >= policy.max_attempts:
                raise
            sleep(policy.delay(attempt))
            continue
        except PermanentIntegrationError:
            # A rejected request is the caller's problem. It does not mean the dependency is down.
            raise
        breaker.record_success()
        return result, attempt
