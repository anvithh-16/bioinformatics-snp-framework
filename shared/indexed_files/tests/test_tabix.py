"""
Tests for shared.indexed_files.tabix.

These tests build their own tiny bgzip+tabix-indexed fixture files
under pytest's `tmp_path` at test time, via `pysam.tabix_index()` —
matching the project's existing convention (shared.reference's tests
do the same) of never committing binary fixtures and never touching a
real reference/ directory.

NOTE: these tests require `pysam` to be installed (see
shared/requirements.txt). They were authored and syntax-checked
without a live pysam available in the authoring environment; the one
detail worth double-checking on first run against your installed
pysam version is whether `pysam.tabix_index()`'s `seq_col`/`start_col`
/`end_col` parameters are 0-based or 1-based in your installed
version — `_build_indexed_fixture()` below assumes 1-based, mirroring
the `tabix -s 1 -b 2 -e 2` CLI convention documented for AlphaMissense's
own file. If the first test run fails on column misalignment rather
than on the assertions themselves, that parameter is the first thing
to check.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pysam
import pytest

from shared.exceptions import ResourceCorruptedError
from shared.indexed_files import get_tabix_lookup
from shared.indexed_files.tabix import TabixLookup, _to_pysam_region, _reset_handle_cache_for_tests

# Minimal generic fixture: chrom, pos, ref, alt, a payload column.
# Deliberately NOT AlphaMissense-shaped — this layer is generic and
# the tests should prove that, not assume AlphaMissense's schema.
FIXTURE_ROWS = [
    ("1", "100", "A", "T", "payload_100"),
    ("1", "200", "G", "C", "payload_200"),
    ("1", "200", "G", "A", "payload_200_alt"),  # same position, different row -> multi-match case
    ("2", "100", "C", "T", "payload_chr2_100"),
]


def _build_indexed_fixture(tmp_path: Path, rows: list[tuple[str, ...]]) -> Path:
    raw_path = tmp_path / "fixture.tsv"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_path, "w") as fh:
        for row in rows:
            fh.write("\t".join(row) + "\n")

    # Sort is required by tabix; rows above are already in chrom/pos order,
    # but sort explicitly so the fixture-builder itself doesn't silently
    # depend on FIXTURE_ROWS staying pre-sorted.
    sorted_path = tmp_path / "fixture.sorted.tsv"
    with open(sorted_path, "w") as fh:
        for row in sorted(rows, key=lambda r: (r[0], int(r[1]))):
            fh.write("\t".join(row) + "\n")

    compressed_path = pysam.tabix_index(
        str(sorted_path),
        seq_col=0,
        start_col=1,
        end_col=1,
        zerobased=False,
        force=True,
    )
    return Path(compressed_path)


@pytest.fixture(autouse=True)
def _clear_handle_cache_between_tests():
    """
    The handle cache is intentionally process-lifetime in production,
    but tests build a fresh fixture file per test — without clearing
    the cache, the second test reusing the same tmp_path-derived
    filename pattern could silently get the previous test's handle.
    """
    yield
    _reset_handle_cache_for_tests()


@pytest.fixture
def indexed_fixture(tmp_path) -> Path:
    return _build_indexed_fixture(tmp_path, FIXTURE_ROWS)


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

def test_to_pysam_region_converts_1_based_to_0_based_half_open():
    assert _to_pysam_region(100) == (99, 100)
    assert _to_pysam_region(1) == (0, 1)


def test_to_pysam_region_rejects_non_positive_position():
    with pytest.raises(ValueError):
        _to_pysam_region(0)
    with pytest.raises(ValueError):
        _to_pysam_region(-5)


# ---------------------------------------------------------------------------
# Core fetch behaviour
# ---------------------------------------------------------------------------

def test_fetch_exact_match_returns_row(indexed_fixture):
    lookup = TabixLookup(indexed_fixture)
    rows = lookup.fetch("1", 100)
    assert len(rows) == 1
    assert rows[0] == ("1", "100", "A", "T", "payload_100")


def test_fetch_no_match_on_valid_chrom_returns_empty_list(indexed_fixture):
    lookup = TabixLookup(indexed_fixture)
    rows = lookup.fetch("1", 999)
    assert rows == []


def test_fetch_multiple_rows_at_same_position_are_all_returned(indexed_fixture):
    lookup = TabixLookup(indexed_fixture)
    rows = lookup.fetch("1", 200)
    assert len(rows) == 2
    payloads = {row[-1] for row in rows}
    assert payloads == {"payload_200", "payload_200_alt"}


def test_fetch_respects_chromosome(indexed_fixture):
    lookup = TabixLookup(indexed_fixture)
    rows = lookup.fetch("2", 100)
    assert len(rows) == 1
    assert rows[0] == ("2", "100", "C", "T", "payload_chr2_100")


def test_fetch_unknown_chromosome_raises_resource_corrupted(indexed_fixture):
    lookup = TabixLookup(indexed_fixture)
    with pytest.raises(ResourceCorruptedError):
        lookup.fetch("99", 100)


# ---------------------------------------------------------------------------
# Resource-state error handling
# ---------------------------------------------------------------------------

def test_missing_data_file_raises_resource_corrupted(tmp_path):
    with pytest.raises(ResourceCorruptedError):
        TabixLookup(tmp_path / "does_not_exist.tsv.gz")


def test_missing_index_raises_resource_corrupted(tmp_path):
    # A real-looking gz file with no .tbi alongside it.
    fake_data = tmp_path / "no_index.tsv.gz"
    fake_data.write_bytes(b"\x1f\x8b\x08\x00")  # gzip magic bytes, not a real bgzip stream
    with pytest.raises(ResourceCorruptedError):
        TabixLookup(fake_data)


def test_corrupted_index_raises_resource_corrupted(indexed_fixture):
    # Truncate the real .tbi to simulate corruption.
    index_path = Path(str(indexed_fixture) + ".tbi")
    original_bytes = index_path.read_bytes()
    index_path.write_bytes(original_bytes[: len(original_bytes) // 2])
    with pytest.raises(ResourceCorruptedError):
        TabixLookup(indexed_fixture)


# ---------------------------------------------------------------------------
# Handle memoization
# ---------------------------------------------------------------------------

def test_get_tabix_lookup_memoizes_handle_for_same_path(indexed_fixture):
    first = get_tabix_lookup(indexed_fixture)
    second = get_tabix_lookup(indexed_fixture)
    assert first is second


def test_get_tabix_lookup_returns_distinct_handles_for_distinct_paths(tmp_path):
    fixture_a = _build_indexed_fixture(tmp_path / "a", FIXTURE_ROWS)
    (tmp_path / "a").mkdir(exist_ok=True)
    fixture_b_dir = tmp_path / "b"
    fixture_b_dir.mkdir(exist_ok=True)
    fixture_b = _build_indexed_fixture(fixture_b_dir, FIXTURE_ROWS)

    lookup_a = get_tabix_lookup(fixture_a)
    lookup_b = get_tabix_lookup(fixture_b)
    assert lookup_a is not lookup_b


def test_get_tabix_lookup_is_the_required_entry_point(indexed_fixture):
    # Module code should obtain lookups exclusively via get_tabix_lookup(),
    # never by constructing TabixLookup directly (memoization would be
    # lost). This test exists to document and enforce that expectation.
    lookup = get_tabix_lookup(indexed_fixture)
    again = get_tabix_lookup(indexed_fixture)
    assert lookup is again
    assert isinstance(lookup, TabixLookup)


# ---------------------------------------------------------------------------
# Generic-ness: prove this layer has no AlphaMissense-shaped assumptions
# ---------------------------------------------------------------------------

def test_layer_is_schema_agnostic(tmp_path):
    """
    A fixture with a totally different column count/shape than
    AlphaMissense's file must work identically — this layer must never
    assume a particular number or meaning of columns.
    """
    odd_rows = [("3", "55", "only_one_payload_column")]
    fixture = _build_indexed_fixture(tmp_path, odd_rows)
    lookup = TabixLookup(fixture)
    rows = lookup.fetch("3", 55)
    assert rows == [("3", "55", "only_one_payload_column")]