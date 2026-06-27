import time

import pytest

from shared.http.rate_limit import RateLimiter
from shared.http.retry import retry_with_backoff


def test_rate_limiter_blocks_when_exhausted():
    limiter = RateLimiter(rate_per_second=5, burst=1)
    limiter.acquire()  # consumes the only token immediately
    start = time.monotonic()
    limiter.acquire()  # must wait ~0.2s for next token
    elapsed = time.monotonic() - start
    assert elapsed > 0.1


def test_rate_limiter_allows_burst():
    limiter = RateLimiter(rate_per_second=5, burst=3)
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05  # burst should not block


def test_retry_succeeds_after_transient_failures():
    calls = {"count": 0}

    @retry_with_backoff(max_retries=3, base_delay=0.01, retry_on=(ValueError,))
    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ValueError("transient")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 3


def test_retry_raises_after_max_retries():
    @retry_with_backoff(max_retries=2, base_delay=0.01, retry_on=(ValueError,))
    def always_fails():
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        always_fails()
