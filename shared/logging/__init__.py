"""
shared.logging
===============

Centralized logging for every module. Future modules should do:

    from shared.logging import get_logger
    log = get_logger(__name__)
    log.info("annotating variant", extra={"variant": "1:12345:A:G"})

Design goals
------------
- One logging configuration for the whole framework — no module configures
  its own handlers/formatters.
- Human-readable console output during development, optional JSON-line
  file output for later parsing/debugging across 12 modules.
- A `timed` decorator/context-manager so execution-time logging (useful
  for spotting slow API calls — gnomAD, VEP, STRING, etc.) is consistent
  everywhere instead of each module hand-rolling timers.
"""

from __future__ import annotations

import functools
import json
import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    """Optional structured formatter for file output."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Anything passed via `extra={...}` ends up on the record's __dict__;
        # pull out the standard LogRecord attrs and keep the rest.
        standard = set(logging.LogRecord(
            "", 0, "", 0, "", (), None).__dict__.keys())
        for key, value in record.__dict__.items():
            if key not in standard and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(
    *,
    level: int = logging.INFO,
    log_dir: Optional[Path] = None,
    json_file_output: bool = True,
) -> None:
    """Configure the root framework logger once. Safe to call multiple
    times — subsequent calls are no-ops. Should be called once at
    application/pipeline startup (e.g. from shared.config on import),
    not from inside individual modules.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger("framework")
    root.setLevel(level)
    root.propagate = False

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(console_handler)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "framework.log")
        if json_file_output:
            file_handler.setFormatter(_JsonFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
                )
            )
        root.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under 'framework.<name>'. Every module
    should call this with __name__ so log lines are traceable to their
    source module (VEP, gnomAD, STRING, ...).
    """
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(f"framework.{name}")


@contextmanager
def timed(logger: logging.Logger, action: str, **extra: Any) -> Iterator[None]:
    """Context manager that logs the duration of a block.

    Usage:
        with timed(log, "vep_rest_call", variant=variant_id):
            response = http_client.get(...)
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(f"{action} completed", extra={"duration_ms": round(elapsed_ms, 2), **extra})


def timed_call(action: Optional[str] = None) -> Callable:
    """Decorator version of `timed`, for wrapping whole functions
    (e.g. a module's annotate() entrypoint) without restructuring code.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log = get_logger(func.__module__)
            label = action or func.__name__
            with timed(log, label):
                return func(*args, **kwargs)
        return wrapper
    return decorator
