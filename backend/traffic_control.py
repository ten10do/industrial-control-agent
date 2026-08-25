import random
import threading
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    max_requests: int = 10
    window_seconds: float = 60.0
    max_concurrent: int = 3
    request_timeout_seconds: float = 110.0


class RateLimitExceeded(RuntimeError):
    pass


class ConcurrencyLimitExceeded(RuntimeError):
    pass


class RequestTimeoutExceeded(RuntimeError):
    pass


class SlidingWindowRateLimiter:
    """Thread-safe per-key sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._lock = threading.Lock()
        self._timestamps: dict[str, list[float]] = defaultdict(list)

    def acquire(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._timestamps[key]
            cutoff = now - self._window
            while window and window[0] < cutoff:
                window.pop(0)
            if len(window) >= self._max_requests:
                return False
            window.append(now)
            return True


class ConcurrencyLimiter:
    """Thread-safe semaphore-style concurrency limiter."""

    def __init__(self, max_concurrent: int) -> None:
        self._semaphore = threading.BoundedSemaphore(max_concurrent)

    def acquire(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def release(self) -> None:
        self._semaphore.release()


_DEFAULT_CONFIG = RateLimitConfig()
_rate_limiter = SlidingWindowRateLimiter(_DEFAULT_CONFIG.max_requests, _DEFAULT_CONFIG.window_seconds)
_concurrency_limiter = ConcurrencyLimiter(_DEFAULT_CONFIG.max_concurrent)


def _client_ip(*args: str) -> str:
    """Derive a rate-limit key from forwarded headers or a fallback identifier."""
    for candidate in args:
        if candidate:
            return candidate
    return "unknown"


def acquire_request(ip: str, x_forwarded: str, request_timeout: float | None = None) -> None:
    key = _client_ip(ip, x_forwarded)

    if not _rate_limiter.acquire(key):
        raise RateLimitExceeded(f"Rate limit exceeded ({_DEFAULT_CONFIG.max_requests} req/{_DEFAULT_CONFIG.window_seconds:.0f}s)")

    if not _concurrency_limiter.acquire():
        raise ConcurrencyLimitExceeded(f"Too many concurrent requests (max {_DEFAULT_CONFIG.max_concurrent})")


def release_request() -> None:
    _concurrency_limiter.release()


def jittered_backoff(base_seconds: float, attempt: int, max_jitter: float = 0.5) -> float:
    """Exponential backoff with uniform jitter."""
    raw = base_seconds * (2 ** attempt)
    return raw + random.uniform(0, max_jitter * raw)


def reset_rate_limiter() -> None:
    """Reset rate limiter state. Intended for test fixtures only."""
    global _rate_limiter
    _rate_limiter = SlidingWindowRateLimiter(_DEFAULT_CONFIG.max_requests, _DEFAULT_CONFIG.window_seconds)
