"""
shared.http.retry
===================

Generic retry-with-exponential-backoff decorator/helper. Not tied to HTTP
specifically (though that's its main use here) so it could also wrap, e.g.,
a flaky local subprocess call (MutPred2/AlphaFold tooling) in the future.
"""

from __future__ import annotations

import functools
import random
import time
from typing import Callable, TypeVar

from shared.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    *,
    max_retries: int = 4,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    jitter: bool = True,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: retries the wrapped function on the given exception
    types using exponential backoff with optional jitter.

    delay = min(max_delay, base_delay * 2**attempt) [+/- jitter]

    `retry_on` should be narrowed by callers to the specific exceptions
    that represent a transient condition (e.g. NetworkError), not bare
    Exception, in real call sites — left generic here since this module
    has no knowledge of which exceptions a given API client considers
    retryable.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except retry_on as exc:
                    attempt += 1
                    if attempt > max_retries:
                        log.error(
                            "max retries exceeded",
                            extra={"function": func.__name__, "attempts": attempt},
                        )
                        raise
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    if jitter:
                        delay *= random.uniform(0.8, 1.2)
                    log.warning(
                        "retrying after error",
                        extra={
                            "function": func.__name__,
                            "attempt": attempt,
                            "delay_seconds": round(delay, 2),
                            "error": str(exc),
                        },
                    )
                    time.sleep(delay)

        return wrapper

    return decorator
