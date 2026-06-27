"""
shared.http
=============

Public surface:
    HttpClient   — instantiate via HttpClient.for_service("ensembl_vep")
    HttpResponse — normalized response object
    retry_with_backoff — generic retry decorator (used internally, also
                          reusable for non-HTTP transient operations)
    get_rate_limiter — process-wide per-service rate limiter accessor
"""

from shared.http.client import HttpClient, HttpResponse
from shared.http.retry import retry_with_backoff
from shared.http.rate_limit import get_rate_limiter, RateLimiter

__all__ = [
    "HttpClient",
    "HttpResponse",
    "retry_with_backoff",
    "get_rate_limiter",
    "RateLimiter",
]
