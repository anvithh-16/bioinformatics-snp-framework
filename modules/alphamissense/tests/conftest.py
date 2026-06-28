from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

import modules.alphamissense.annotator as annotator_module
import modules.alphamissense.client as client_module
from shared.exceptions import UnknownResourceError
from shared.indexed_files import _reset_handle_cache_for_tests

# (chrom [file-style], pos, ref, alt, genome, uniprot_id, transcript_id,
#  protein_variant, am_pathogenicity, am_class)
#
# Coordinates for TP53 R175H and APOE rs429358 mirror the real,
# well-known variants used in the frozen biological sanity-check plan
# (Conversation 4A, section 22). The am_pathogenicity/am_class values
# here are illustrative and consistent with the published direction of
# each variant (R175H pathogenic hotspot; APOE4 a common risk-modifying
# polymorphism rather than a classic monogenic-pathogenic missense),
# but they are NOT pulled from the real downloaded AlphaMissense_hg38
# file. These tests validate pipeline mechanics against a realistic
# synthetic fixture; re-running test_sanity.py against the real pinned
# file is required before treating this as a genuine biological sanity
# check.
SAMPLE_ROWS = [
    ("chr17", "7674220", "C", "T", "hg38", "P04637", "ENST00000269305.9", "R175H", "0.9938", "likely_pathogenic"),
    ("chr19", "44908684", "T", "C", "hg38", "P02649", "ENST00000252486.9", "C130R", "0.0823", "likely_benign"),
    ("chr1", "1000000", "A", "G", "hg38", "Q9XXXX1", "ENST00000000001.1", "K1E", "0.5000", "ambiguous"),
    # Same exact position+allele scored on two different transcripts --
    # the rare overlapping-gene collision case (status=multiple_matches).
    ("chr5", "5000000", "G", "T", "hg38", "Q1AAAA1", "ENST00000111111.1", "V10L", "0.7000", "likely_pathogenic"),
    ("chr5", "5000000", "G", "T", "hg38", "Q2BBBB2", "ENST00000222222.1", "M20I", "0.3000", "likely_benign"),
    # Same position as the chr1 row above but a DIFFERENT alternate allele --
    # must be filtered out (not counted as ambiguity) when querying A>G.
    ("chr1", "1000000", "A", "C", "hg38", "Q9YYYY1", "ENST00000000002.1", "K1Q", "0.1000", "likely_benign"),
]

RESOURCE_VERSION = "zenodo:test-fixture-v1"


# ---------------------------------------------------------------------------
# Test-local fakes. These are NOT part of, and do not require any change
# to, shared.reference or shared.config. They stand in for whatever the
# real ReferenceManager/FrameworkConfig return, relying only on the
# public attributes the AlphaMissense module itself already depends on:
#   - a resource handle with `.path` and `.version` (client.py)
#   - a config object with `.cache_dir` (annotator.py)
#   - shared.exceptions.UnknownResourceError for an unregistered resource
#     (the real, documented exception -- not a fabricated helper)
# They are wired in by monkeypatching the `get_reference_manager` /
# `get_config` names as imported into modules.alphamissense.client and
# modules.alphamissense.annotator respectively, which is the standard
# way to isolate a unit under test from a real singleton without
# requiring the singleton's module to expose any test-only API.
# ---------------------------------------------------------------------------


@dataclass
class FakeResourceHandle:
    path: str
    version: str


class FakeReferenceManager:
    def __init__(self):
        self._resource: Optional[FakeResourceHandle] = None
        self._error: Optional[Exception] = None

    def set_resource(self, path, version: str) -> None:
        self._resource = FakeResourceHandle(path=str(path), version=version)
        self._error = None

    def set_error(self, exc: Exception) -> None:
        self._error = exc
        self._resource = None

    def get(self, name: str) -> FakeResourceHandle:
        if self._error is not None:
            raise self._error
        if self._resource is None:
            raise UnknownResourceError(f"Unknown resource: {name}", context={"resource": name})
        return self._resource


@dataclass
class FakeFrameworkConfig:
    cache_dir: Path


@pytest.fixture(autouse=True)
def fake_reference_manager(monkeypatch):
    """
    Patches modules.alphamissense.client.get_reference_manager for the
    duration of each test, so every test is isolated from whatever
    resources are or aren't registered in the real framework -- this is
    what makes test_missing_resource_raises_unknown_resource_error_not_swallowed
    deterministic regardless of the real config.yaml's actual state.
    """
    manager = FakeReferenceManager()
    monkeypatch.setattr(client_module, "get_reference_manager", lambda: manager)
    return manager


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    """
    Patches modules.alphamissense.annotator.get_config so tests read/write
    a per-test temp cache directory instead of whatever cache_dir the
    real framework config resolves to.
    """
    cfg = FakeFrameworkConfig(cache_dir=tmp_path / "cache")
    monkeypatch.setattr(annotator_module, "get_config", lambda: cfg)
    return cfg


@pytest.fixture(autouse=True)
def _reset_indexed_file_handles():
    yield
    _reset_handle_cache_for_tests()


def write_fixture_file(path, rows=None):
    """
    Builds a real, bgzip-compressed, tabix-indexed fixture file -- not a
    plain .tsv -- because AlphaMissenseClient.fetch_raw_rows() goes
    through shared.indexed_files.get_tabix_lookup(), which requires a
    genuine .tbi index (TabixLookup._open() raises ResourceCorruptedError
    otherwise; this is correct, real infrastructure behavior, not
    something to work around).

    Mirrors shared/indexed_files/tests/test_tabix.py's own
    _build_indexed_fixture() exactly: sort by (chrom, position) -- tabix
    requires sorted input -- then index with pysam.tabix_index() using
    the same 1-based seq_col/start_col/end_col convention already
    verified against the real pysam install in this project.

    `path` is the desired uncompressed filename; the returned Path is
    the resulting `<path>.gz` (or `path` itself if it already ends in
    .gz), since pysam.tabix_index() compresses+indexes in place. Callers
    must use the returned path, not the input `path`.
    """
    import pysam

    rows = SAMPLE_ROWS if rows is None else rows
    path = Path(path)

    with open(path, "w") as fh:
        for row in sorted(rows, key=lambda r: (r[0], int(r[1]))):
            fh.write("\t".join(row) + "\n")

    print("=" * 80)
    print("Fixture file:", path)
    print("Contents:")
    print(path.read_text())
    print("=" * 80)
    
    compressed_path = pysam.tabix_index(
        str(path),
        seq_col=0,
        start_col=1,
        end_col=1,
        zerobased=False,
        force=True,
    )
    return Path(compressed_path)


@pytest.fixture
def fixture_file(tmp_path):
    return write_fixture_file(tmp_path / "AlphaMissense_hg38.test.tsv")


@pytest.fixture
def registered_resource(fixture_file, fake_reference_manager):
    """
    Registers the standard fixture file on the (already-patched) fake
    reference manager and returns the resulting resource handle
    directly, so callers needing it (e.g. test_cache.py) don't need to
    go through get_reference_manager() again themselves.
    """
    fake_reference_manager.set_resource(fixture_file, RESOURCE_VERSION)
    return fake_reference_manager.get("alphamissense")


@pytest.fixture
def registered_resource_error(fake_reference_manager):
    def _register(exc):
        fake_reference_manager.set_error(exc)

    return _register