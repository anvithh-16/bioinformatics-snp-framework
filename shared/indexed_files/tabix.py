"""
shared.indexed_files.tabix
===========================

Generic random-access reader for local, bgzip-compressed, tabix-indexed
flat files (TSV, BED, VCF-like, or any other tab-delimited format that
has been indexed with `tabix`).

This module knows nothing about any specific module's columns. It does
exactly one job: given a file path, a chromosome, and a 1-based genomic
position, return the raw matching row(s) as tuples of strings. Turning
those raw tuples into a domain-specific annotation (AlphaMissense fields,
SpliceAI scores, etc.) is the caller's responsibility, not this layer's.

Frozen design notes (Conversation 4A, AlphaMissense architecture review):
  - Coordinates everywhere else in this project are 1-based. pysam's
    TabixFile.fetch() uses Python's 0-based, half-open convention. The
    conversion happens in exactly one place: `_to_pysam_region()` below.
  - TabixFile handles are expensive to open (the index is loaded into
    memory) and must not be reopened per lookup. `get_tabix_lookup()`
    memoizes one handle per resolved file path for the lifetime of the
    process.
  - A single TabixFile handle is not guaranteed safe for concurrent
    fetch() calls from multiple threads. This is a documented limitation
    (consistent with shared.http.RateLimiter's per-process caveat), not
    a bug: if the pipeline is ever parallelized across threads, each
    worker should call get_tabix_lookup() itself to obtain its own
    handle — this is cheap because handles are memoized per-process,
    not per-call.
  - Missing or corrupted index files are treated as a resource-state
    problem and raise shared.exceptions.ResourceCorruptedError — the
    same exception shared.reference already uses for a resource that
    is present but unusable. No new exception type is introduced.

Reused by: modules/alphamissense/ (Conversation 4B). Intended to also be
reused by the future SpliceAI and gnomAD-local-fallback modules without
modification — do not add AlphaMissense-specific (or any module-specific)
logic to this file.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import pysam

from shared.exceptions import ResourceCorruptedError
from shared.logging import get_logger

log = get_logger(__name__)

# Process-level cache of open TabixFile handles, keyed by resolved
# absolute file path. Never cleared during the life of the process;
# handles are cheap to keep open and expensive to reopen.
_HANDLE_CACHE: dict[str, "TabixLookup"] = {}
_HANDLE_CACHE_LOCK = threading.Lock()


class TabixLookup:
    """
    Random-access reader for a single bgzip-compressed, tabix-indexed
    flat file.

    Not domain-aware: `fetch()` returns raw tab-split rows as tuples of
    strings. Callers are responsible for interpreting columns.

    Not guaranteed thread-safe for concurrent fetch() calls on the same
    instance. Obtain one instance per thread via get_tabix_lookup() if
    the pipeline is ever parallelized; instances are memoized per file
    path, so this does not multiply the number of open file handles
    beyond one per (file, thread).
    """

    def __init__(self, file_path: str | Path, index_path: Optional[str | Path] = None):
        self.file_path = str(Path(file_path).resolve())
        self._index_path = str(Path(index_path).resolve()) if index_path else None
        self._tabix_file: Optional[pysam.TabixFile] = None
        self._open()

    def _open(self) -> None:
        path = Path(self.file_path)
        if not path.is_file():
            raise ResourceCorruptedError(
                "Indexed file does not exist on disk",
                context={"file_path": self.file_path},
            )

        index_path = Path(self._index_path) if self._index_path else Path(self.file_path + ".tbi")
        if not index_path.is_file():
            raise ResourceCorruptedError(
                "Tabix index (.tbi) is missing for an indexed resource file; "
                "the resource is present but not usable until it is (re)indexed",
                context={"file_path": self.file_path, "expected_index": str(index_path)},
            )

        try:
            self._tabix_file = pysam.TabixFile(self.file_path, index=str(index_path))
        except Exception as exc:  # pysam raises plain OSError/ValueError on corrupt index/file
            raise ResourceCorruptedError(
                "Failed to open tabix-indexed file; the index may be corrupted "
                "or built against a different version of the data file",
                context={"file_path": self.file_path, "index_path": str(index_path)},
            ) from exc

        log.debug(
            "Opened tabix-indexed file",
            extra={"file_path": self.file_path, "index_path": str(index_path)},
        )

    def fetch(self, chrom: str, position: int) -> list[tuple[str, ...]]:
        """
        Return every row whose interval covers the given 1-based genomic
        position on the given chromosome, as raw tab-split tuples.

        `position` follows this project's standard convention: 1-based,
        matching `annotate(chrom, position, reference, alternate)`. The
        conversion to pysam's 0-based, half-open fetch() convention is
        performed internally.

        Returns an empty list if nothing matches at that coordinate —
        this is a normal, expected outcome (e.g. the variant simply
        isn't in the indexed dataset), not an error condition. Callers
        decide what an empty result means biologically (e.g. "no_data").

        Raises ResourceCorruptedError if the underlying contig is not
        present in the index at all (distinct from "no row at this
        position on a contig that does exist") — this usually signals a
        chromosome-naming mismatch between the query and the indexed
        file (e.g. "chr1" vs "1") rather than a genuine absence of data,
        and is surfaced rather than silently swallowed.
        """
        start, end = _to_pysam_region(position)
        try:
            rows = list(self._tabix_file.fetch(chrom, start, end))
        except ValueError as exc:
            # pysam raises ValueError for "contig not in index" — distinct
            # from "no rows in a valid contig", which returns cleanly.
            raise ResourceCorruptedError(
                "Chromosome not found in tabix index; check chromosome "
                "naming convention (e.g. 'chr1' vs '1') against the "
                "indexed file",
                context={"file_path": self.file_path, "chrom": chrom, "position": position},
            ) from exc

        return [tuple(row.split("\t")) for row in rows]

    def close(self) -> None:
        if self._tabix_file is not None:
            self._tabix_file.close()
            self._tabix_file = None


def _to_pysam_region(position: int) -> tuple[int, int]:
    """
    Convert a 1-based genomic position into the 0-based, half-open
    (start, end) region pysam's TabixFile.fetch() expects.

    This is the single, frozen location for this conversion in the
    entire project. No other module should re-derive it.
    """
    if position < 1:
        raise ValueError(f"position must be 1-based and >= 1, got {position}")
    return position - 1, position


def get_tabix_lookup(file_path: str | Path, index_path: Optional[str | Path] = None) -> TabixLookup:
    """
    Return the memoized TabixLookup for the given file path, opening and
    caching a new handle on first use. Safe to call repeatedly — this is
    the only way modules should obtain a TabixLookup; do not construct
    TabixLookup directly in module code, or handle memoization is lost.
    """
    resolved = str(Path(file_path).resolve())
    with _HANDLE_CACHE_LOCK:
        existing = _HANDLE_CACHE.get(resolved)
        if existing is not None:
            return existing
        lookup = TabixLookup(file_path, index_path=index_path)
        _HANDLE_CACHE[resolved] = lookup
        return lookup


def _reset_handle_cache_for_tests() -> None:
    """
    Test-only helper. Production code must never call this — handle
    memoization is intentionally permanent for the life of the process.
    """
    with _HANDLE_CACHE_LOCK:
        for handle in _HANDLE_CACHE.values():
            handle.close()
        _HANDLE_CACHE.clear()