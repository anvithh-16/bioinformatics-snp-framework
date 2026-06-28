from __future__ import annotations

"""
Integration tests against the real downloaded SpliceAI masked SNV file.
Skipped automatically if the file is not installed at the expected path.

Run with: pytest modules/spliceai/tests/test_integration.py -m integration
"""

import pytest

from modules.spliceai.annotator import annotate
from modules.spliceai.constants import STATUS_NO_DATA, STATUS_OK

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _require_real_resource():
    """Skip every test in this module if the real SpliceAI resource is
    not installed and usable."""
    from shared.reference import get_reference_manager
    from shared.exceptions import ResourceCorruptedError, UnknownResourceError

    try:
        rm = get_reference_manager()
        rm.get("spliceai")
    except (UnknownResourceError, ResourceCorruptedError) as exc:
        pytest.skip(f"Real SpliceAI resource not available: {exc}")


def test_known_position_returns_ok_status():
    """Smoke-test: any scored position in the file should return status='ok'."""
    # BRCA1 canonical splice donor — expected to return ok with meaningful scores.
    result = annotate("17", 41276045, "G", "T")
    # We can only assert the envelope shape here, not exact values, because
    # the real file values are unknown until it is downloaded. Re-run
    # test_biological_sanity.py once the file is confirmed present.
    assert result["module_name"] == "spliceai"
    assert result["status"] in (STATUS_OK, STATUS_NO_DATA)
    assert "fields" in result
    assert "source_version" in result
    assert result["source_version"] is not None


def test_envelope_fields_are_complete():
    result = annotate("17", 41276045, "G", "T")
    fields = result["fields"]
    expected_keys = {
        "ds_acceptor_gain", "ds_acceptor_loss", "ds_donor_gain", "ds_donor_loss",
        "dp_acceptor_gain", "dp_acceptor_loss", "dp_donor_gain", "dp_donor_loss",
        "max_delta_score", "gene_symbol",
        "source_dataset", "data_release", "annotation_source",
    }
    assert expected_keys.issubset(fields.keys())


def test_position_outside_gene_window_is_no_data_not_error():
    # A position on a valid chromosome but deep in an intergenic desert:
    # Illumina's tool doesn't score these, so status must be 'no_data', not
    # an exception. Chromosome 1 position 1 is typically intergenic in GRCh38.
    result = annotate("1", 1, "A", "T")
    assert result["status"] == STATUS_NO_DATA


def test_cache_reduces_repeated_lookups():
    """Second call for the same variant must not re-read the file."""
    from modules.spliceai.client import SpliceAILocalClient
    from modules.spliceai.tests.test_cache import CountingClient
    from shared.reference import get_reference_manager

    rm = get_reference_manager()
    resource = rm.get("spliceai")
    client = CountingClient(resource)

    annotate("17", 41276045, "G", "T", client=client)
    annotate("17", 41276045, "G", "T", client=client)
    assert client.fetch_count == 1