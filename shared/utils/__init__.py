"""
shared.utils
==============

Small generic helpers that don't belong in any other shared submodule.
Kept deliberately minimal — anything biology-specific does NOT belong
here (it belongs in a module's own internal code, once modules exist).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")


def chunked(items: list[T], size: int) -> Iterator[list[T]]:
    """Split a list into chunks of at most `size` — useful for batching
    requests to APIs with batch endpoints (VEP REST supports POST batches).
    """
    for i in range(0, len(items), size):
        yield items[i:i + size]


def disk_usage_gb(path: Path) -> float:
    """Total used disk space in GB for the filesystem containing `path`.
    Used by the storage-safety-brake pattern (generalized from the
    MutPred2 extraction problem) before any large download/extraction.
    """
    usage = shutil.disk_usage(path)
    return usage.used / (1024 ** 3)


def free_disk_gb(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024 ** 3)


def ensure_free_space(path: Path, required_gb: float) -> None:
    """Raise if there isn't enough free space for an operation about to
    happen (e.g. extracting a large tarball). This is the generalized
    version of the disk-safety-brake first built for MutPred2 — every
    module dealing with large downloads (AlphaFold cache fills, dbNSFP,
    optional MutPred2 BLAST DB) should call this before writing.
    """
    from shared.exceptions import FrameworkError

    available = free_disk_gb(path)
    if available < required_gb:
        raise FrameworkError(
            f"Insufficient disk space at {path}: need {required_gb:.1f}GB, "
            f"only {available:.1f}GB free",
            context={"path": str(path), "required_gb": required_gb, "available_gb": available},
        )


def directory_size_gb(path: Path) -> float:
    """Recursively compute a directory's size in GB. Used for monitoring
    the shared reference/ and cache/ directories against the 200GB project
    budget without needing external tools.
    """
    total_bytes = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    return total_bytes / (1024 ** 3)
