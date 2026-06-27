"""
shared.http.rate_limit
=======================

A per-service token-bucket rate limiter. One instance per external API
(Ensembl, gnomAD, STRING, GWAS Catalog, AlphaFold DB, ...), each configured
independently via shared.config, so a single shared implementation supports
every module without per-module rewrites.

Thread-safety: a single `RateLimiter` instance is safe to share across
threads within one process (e.g. if a module parallelizes annotation
requests). It is NOT safe across separate processes — if modules ever run
as separate processes hitting the same API, each process gets its own
token bucket and the *effective* combined rate could exceed the service's
real limit. This is a known limitation, see Section "Potential Improvements".
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class RateLimiterStats:
    total_requests: int = 0
    total_wait_seconds: float = 0.0


class RateLimiter:
    """Token-bucket rate limiter.

    Allows up to `rate_per_second` requests per second, with bursts up to
    `burst` tokens. Call `.acquire()` before making a request; it blocks
    (sleeps) only as long as necessary.
    """

    def __init__(self, rate_per_second: float, burst: int | None = None):
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._rate = rate_per_second
        self._capacity = burst if burst is not None else max(1, int(rate_per_second))
        self._tokens = float(self._capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self.stats = RateLimiterStats()

    def acquire(self, tokens: int = 1) -> None:
        """Block until `tokens` are available, then consume them."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self.stats.total_requests += 1
                    return
                deficit = tokens - self._tokens
                wait_time = deficit / self._rate
            time.sleep(wait_time)
            self.stats.total_wait_seconds += wait_time

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now


class RateLimiterRegistry:
    """Holds one RateLimiter per named service so callers don't need to
    construct/wire limiters themselves. Configuration is pulled from
    shared.config so limits live in one place (config.yaml), not scattered
    across module code.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = threading.Lock()

    def get(self, service_name: str, rate_per_second: float) -> RateLimiter:
        with self._lock:
            if service_name not in self._limiters:
                self._limiters[service_name] = RateLimiter(rate_per_second)
            return self._limiters[service_name]


_REGISTRY = RateLimiterRegistry()


def get_rate_limiter(service_name: str, rate_per_second: float) -> RateLimiter:
    """Process-wide accessor — every module calls this with its own
    service name and configured rate, and gets back a shared limiter
    instance for that service.
    """
    return _REGISTRY.get(service_name, rate_per_second)
