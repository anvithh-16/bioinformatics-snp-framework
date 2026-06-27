from __future__ import annotations

import pytest

from shared.indexed_files import _reset_handle_cache_for_tests
from shared.reference import (
    _clear_registry_for_tests,
    _set_resource_error_for_tests,
    _set_resource_for_tests,
)

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
# file -- this sandbox has no network access to fetch it. These tests
# validate pipeline mechanics against a realistic synthetic fixture;
# re-running test_sanity.py against the real pinned file in your
# environment is required before treating this as a genuine biological
# sanity check.
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


@pytest.fixture(autouse=True)
def _clean_shared_state(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAMEWORK_TEST_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("FRAMEWORK_TEST_REFERENCE_DIR", str(tmp_path / "reference"))
    yield
    _clear_registry_for_tests()
    _reset_handle_cache_for_tests()


def write_fixture_file(path, rows=SAMPLE_ROWS):
    with open(path, "w") as fh:
        for row in rows:
            fh.write("\t".join(row) + "\n")
    return path


@pytest.fixture
def fixture_file(tmp_path):
    return write_fixture_file(tmp_path / "AlphaMissense_hg38.test.tsv")


@pytest.fixture
def registered_resource(fixture_file):
    _set_resource_for_tests("alphamissense", fixture_file, RESOURCE_VERSION)
    return fixture_file


@pytest.fixture
def registered_resource_error():
    def _register(exc):
        _set_resource_error_for_tests("alphamissense", exc)

    return _register