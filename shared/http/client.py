"""
shared.http.client
=====================

A single, generic HTTP client every API-based module reuses (VEP/Ensembl,
gnomAD, STRING, GWAS Catalog, AlphaFold DB, SpliceAI-if-API-based, ...).

No service-specific logic lives here. A module instantiates a client via
`HttpClient.for_service("ensembl_vep")`, which pulls base_url/timeout/
retries/rate-limit from shared.config, and the module only supplies the
path and params for its specific endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests

from shared.config import get_config
from shared.exceptions import NetworkError, RateLimitError
from shared.http.rate_limit import get_rate_limiter
from shared.http.retry import retry_with_backoff
from shared.logging import get_logger, timed

log = get_logger(__name__)


@dataclass
class HttpResponse:
    """Normalized response object so callers never touch `requests`
    objects directly — keeps the underlying HTTP library swappable.
    """
    status_code: int
    url: str
    json_body: Optional[Any]
    text: str
    headers: dict[str, str]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise NetworkError(
                f"HTTP {self.status_code} from {self.url}",
                context={"status_code": self.status_code, "url": self.url,
                         "body_snippet": self.text[:500]},
            )


class HttpClient:
    """Reusable HTTP client with connection pooling, retries, exponential
    backoff, rate limiting, and structured logging built in.

    Construct via `HttpClient.for_service(name)` in normal module code;
    the bare constructor is mainly for tests that need to inject a custom
    base_url/timeout without touching shared.config.
    """

    def __init__(
        self,
        *,
        service_name: str,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        rate_limit_per_second: float,
        default_headers: Optional[dict[str, str]] = None,
    ):
        self.service_name = service_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.default_headers = default_headers or {"Accept": "application/json"}

        self._session = requests.Session()
        # Connection pooling: reuse TCP connections across many requests to
        # the same service — this matters once a module is annotating
        # thousands of variants against one API (gnomAD, VEP).
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        self._rate_limiter = get_rate_limiter(service_name, rate_limit_per_second)

    @classmethod
    def for_service(cls, service_name: str) -> "HttpClient":
        cfg = get_config()
        service_cfg = cfg.service(service_name)
        return cls(
            service_name=service_name,
            base_url=service_cfg.base_url,
            timeout_seconds=service_cfg.timeout_seconds,
            max_retries=service_cfg.max_retries,
            rate_limit_per_second=service_cfg.rate_limit_per_second,
        )

    # -- public API --------------------------------------------------------

    def get(
        self,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> HttpResponse:
        return self._request("GET", path, params=params, headers=headers)

    def post(
        self,
        path: str,
        *,
        json_body: Optional[Any] = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> HttpResponse:
        return self._request("POST", path, params=params, headers=headers, json_body=json_body)

    # -- internals -----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        json_body: Optional[Any] = None,
    ) -> HttpResponse:
        url = f"{self.base_url}/{path.lstrip('/')}"
        merged_headers = {**self.default_headers, **(headers or {})}

        @retry_with_backoff(
            max_retries=self.max_retries,
            retry_on=(NetworkError,),
        )
        def do_request() -> HttpResponse:
            self._rate_limiter.acquire()
            with timed(log, f"{self.service_name}.{method.lower()}", url=url):
                try:
                    raw = self._session.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=merged_headers,
                        timeout=self.timeout_seconds,
                    )
                except requests.exceptions.Timeout as exc:
                    raise NetworkError(
                        f"Request to {url} timed out after {self.timeout_seconds}s",
                        context={"url": url},
                    ) from exc
                except requests.exceptions.RequestException as exc:
                    raise NetworkError(
                        f"Request to {url} failed: {exc}", context={"url": url}
                    ) from exc

            if raw.status_code == 429:
                raise RateLimitError(
                    f"Rate limited by {self.service_name} ({url})",
                    context={"url": url, "status_code": 429},
                )
            if raw.status_code >= 500:
                # Server errors are treated as transient/retryable.
                raise NetworkError(
                    f"Server error {raw.status_code} from {url}",
                    context={"url": url, "status_code": raw.status_code},
                )

            try:
                body = raw.json()
            except ValueError:
                body = None

            return HttpResponse(
                status_code=raw.status_code,
                url=url,
                json_body=body,
                text=raw.text,
                headers=dict(raw.headers),
            )

        return do_request()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
