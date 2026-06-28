from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

import modules.spliceai.annotator as annotator_module
import modules.spliceai.client as client_module
from modules.spliceai.constants import PRIMARY_VCF_FILENAME
from shared.exceptions import UnknownResourceError
from shared.indexed_files import _reset_handle_cache_for_tests

# ---------------------------------------------------------------------------
# Fixture VCF rows
#
# Format: (CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO)
# INFO contains a SpliceAI= field with pipe-delimited entries:
#   ALLELE|SYMBOL|DS_AG|DS_AL|DS_DG|DS_DL|DP_AG|DP_AL|DP_DG|DP_DL
#
# CHROM uses bare Ensembl-style names ("1", "17", "X") — matching the
# real Illumina SpliceAI masked SNV VCF, which does NOT use "chr" prefixes.
#
# Variants chosen to cover:
#   - A high-scoring canonical splice-site disruption (BRCA1 exon 10 donor)
#   - A synonymous exonic variant with low scores
#   - A deep intronic cryptic splice-site creator (high DS_AG)
#   - A multi-allelic position (two ALT alleles in one row via two entries)
#   - A row with '.' fields (partial None handling)
#
# Coordinates are synthetic but use realistic gene/chromosome assignments.
# ---------------------------------------------------------------------------

# 17:41276045 — synthetic BRCA1 splice donor, single ALT
_BRCA1_INFO = "SpliceAI=T|BRCA1|0.02|0.91|0.01|0.03|-2|3|1|-4"
BRCA1_ROW = ("17", "41276045", ".", "G", "T", ".", ".", _BRCA1_INFO)

# 1:69511 — synthetic synonymous exonic variant, low scores
_SYN_INFO = "SpliceAI=T|OR4F5|0.00|0.01|0.00|0.01|2|-3|1|-1"
SYN_ROW = ("1", "69511", ".", "A", "T", ".", ".", _SYN_INFO)

# 2:179415121 — synthetic deep intronic cryptic acceptor gain
_INTRONIC_INFO = "SpliceAI=C|SCN1A|0.87|0.00|0.02|0.00|-15|2|-20|4"
INTRONIC_ROW = ("2", "179415121", ".", "G", "C", ".", ".", _INTRONIC_INFO)

# 5:150000000 — multi-allelic: two ALT alleles (A and C) in one row
_MULTI_INFO = "SpliceAI=A|GENEX|0.55|0.10|0.02|0.03|5|-2|1|-3,C|GENEX|0.01|0.02|0.03|0.01|1|2|3|4"
MULTI_ROW = ("5", "150000000", ".", "G", "A,C", ".", ".", _MULTI_INFO)

# 7:100000000 — row containing '.' fields (partial data)
_DOT_INFO = "SpliceAI=A|DOTGENE|.|0.30|.|0.10|.|5|.|2"
DOT_ROW = ("7", "100000000", ".", "C", "A", ".", ".", _DOT_INFO)

SAMPLE_ROWS = [
    BRCA1_ROW,
    SYN_ROW,
    INTRONIC_ROW,
    MULTI_ROW,
    DOT_ROW,
]

RESOURCE_VERSION = "spliceai:fixture-v1"


# ---------------------------------------------------------------------------
# Test-local fakes (same pattern as AlphaMissense conftest)
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
    _version: str = RESOURCE_VERSION

    def version(self, key: str) -> Optional[str]:
        if key == "spliceai_version":
            return self._version
        return None


@pytest.fixture(autouse=True)
def fake_reference_manager(monkeypatch):
    manager = FakeReferenceManager()
    monkeypatch.setattr(client_module, "get_reference_manager", lambda: manager)
    return manager


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    cfg = FakeFrameworkConfig(cache_dir=tmp_path / "cache")
    monkeypatch.setattr(annotator_module, "get_config", lambda: cfg)
    return cfg


@pytest.fixture(autouse=True)
def _reset_indexed_file_handles():
    yield
    _reset_handle_cache_for_tests()


def write_fixture_vcf(directory, rows=None):
    """
    Build a real bgzip-compressed, tabix-indexed VCF fixture inside
    `directory`. The output file is always named PRIMARY_VCF_FILENAME so
    that SpliceAILocalClient._vcf_path resolves correctly when
    `resource.path` is `directory`.

    Returns the Path to the directory (not the .gz file) so callers can
    pass it directly to FakeReferenceManager.set_resource() without any
    further path manipulation.
    """
    import pysam

    rows = SAMPLE_ROWS if rows is None else rows
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    raw_vcf = directory / (PRIMARY_VCF_FILENAME.replace(".vcf.gz", ".vcf"))

    with open(raw_vcf, "w") as fh:
        fh.write("##fileformat=VCFv4.1\n")
        fh.write('##INFO=<ID=SpliceAI,Number=.,Type=String,Description="SpliceAI variant annotation">\n')
        fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        for row in sorted(rows, key=lambda r: (r[0], int(r[1]))):
            fh.write("\t".join(row) + "\n")

    pysam.tabix_index(
        str(raw_vcf),
        preset="vcf",
        force=True,
    )
    # pysam.tabix_index writes <raw_vcf>.gz and <raw_vcf>.gz.tbi alongside
    # the plain VCF. Confirm the expected name matches PRIMARY_VCF_FILENAME.
    compressed = directory / PRIMARY_VCF_FILENAME
    assert compressed.is_file(), (
        f"pysam.tabix_index produced a different filename than expected. "
        f"Expected: {compressed}"
    )

    return directory


@pytest.fixture
def fixture_resource_dir(tmp_path):
    """Returns the directory containing the fixture VCF + index."""
    return write_fixture_vcf(tmp_path / "spliceai")


@pytest.fixture
def registered_resource(fixture_resource_dir, fake_reference_manager):
    fake_reference_manager.set_resource(fixture_resource_dir, RESOURCE_VERSION)
    return fake_reference_manager.get("spliceai")


@pytest.fixture
def registered_resource_error(fake_reference_manager):
    def _register(exc):
        fake_reference_manager.set_error(exc)
    return _register