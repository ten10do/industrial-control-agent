import threading
import time

import pytest

from backend.traffic_control import (
    ConcurrencyLimiter,
    SlidingWindowRateLimiter,
    jittered_backoff,
)
from backend.llm_client import CircuitBreaker


class TestSlidingWindowRateLimiter:
    def test_allows_requests_within_limit(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60.0)
        for _ in range(5):
            assert limiter.acquire("client-a") is True

    def test_blocks_requests_exceeding_limit(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            assert limiter.acquire("client-a") is True
        assert limiter.acquire("client-a") is False

    def test_separate_keys_have_independent_limits(self) -> None:
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
        assert limiter.acquire("client-a") is True
        assert limiter.acquire("client-a") is True
        assert limiter.acquire("client-a") is False
        assert limiter.acquire("client-b") is True


class TestConcurrencyLimiter:
    def test_acquire_and_release(self) -> None:
        limiter = ConcurrencyLimiter(max_concurrent=2)
        assert limiter.acquire() is True
        assert limiter.acquire() is True
        assert limiter.acquire() is False
        limiter.release()
        assert limiter.acquire() is True

    def test_thread_safety(self) -> None:
        limiter = ConcurrencyLimiter(max_concurrent=3)
        results: list[bool] = []
        lock = threading.Lock()
        barrier = threading.Barrier(3, timeout=5)

        def worker() -> None:
            acquired = limiter.acquire()
            with lock:
                results.append(acquired)
            if acquired:
                barrier.wait()
                limiter.release()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(results) == 6


class TestCircuitBreaker:
    def test_closed_initially(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)
        assert cb.is_open() is False

    def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=30.0)
        cb.record_failure()
        assert cb.is_open() is False
        cb.record_failure()
        assert cb.is_open() is True

    def test_success_resets_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.is_open() is False

    def test_half_open_after_cooldown(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True
        time.sleep(0.02)
        assert cb.is_open() is False


class TestJitteredBackoff:
    def test_backoff_grows_exponentially(self) -> None:
        base = 1.0
        b0 = jittered_backoff(base, 0, max_jitter=0.0)
        b1 = jittered_backoff(base, 1, max_jitter=0.0)
        b2 = jittered_backoff(base, 2, max_jitter=0.0)
        assert b0 == 1.0
        assert b1 == 2.0
        assert b2 == 4.0

    def test_jitter_adds_randomness(self) -> None:
        results = {jittered_backoff(1.0, 0, max_jitter=1.0) for _ in range(50)}
        assert len(results) > 1
