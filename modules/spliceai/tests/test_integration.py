from __future__ import annotations

"""
Integration tests: full annotate() pipeline exercised against the
synthetic fixture VCF built by conftest.py.

These tests run in CI without the real Illumina resource. They verify
that every layer of the module (validation -> cache -> reference manager
-> client -> tabix -> parser -> model -> envelope) works together
correctly. The fixture encodes realistic SpliceAI values whose
direction matches known biology; see test_biological_sanity.py for the
explicit directional assertions.

This matches the AlphaMissense test architecture exactly: all tests in
this file use the fixture-backed fake reference manager wired by
conftest.py's autouse fixtures, so no real resource is required.
Tests against the real downloaded file live in test_real_resource.py.
"""

import pytest

from shared.exceptions import ResourceCorruptedError, UnknownResourceError, ValidationError

from modules.spliceai.annotator import annotate
from modules.spliceai.constants import STATUS_NO_DATA, STATUS_OK


def test_full_pipeline_ok_brca1(registered_resource):
    result = annotate("17", 41276045, "G", "T")
    assert result["status"] == STATUS_OK
    assert result["variant_id"] == "17:41276045:G:T"
    assert result["module_name"] == "spliceai"
    assert result["fields"]["ds_acceptor_loss"] == pytest.approx(0.91)
    assert result["fields"]["gene_symbol"] == "BRCA1"
    assert result["fields"]["max_delta_score"] == pytest.approx(0.91)
    assert result["source_version"] == "spliceai:fixture-v1"


def test_full_pipeline_no_data_for_unknown_position(registered_resource):
    result = annotate("1", 1, "A", "T")
    assert result["status"] == STATUS_NO_DATA
    assert result["fields"]["ds_acceptor_gain"] is None
    assert result["fields"]["max_delta_score"] is None


def test_full_pipeline_no_data_when_allele_not_in_file(registered_resource):
    # 17:41276045 is scored for G>T only; querying G>C should be no_data.
    result = annotate("17", 41276045, "G", "C")
    assert result["status"] == STATUS_NO_DATA


def test_full_pipeline_multi_allele_selects_correct_entry(registered_resource):
    result_a = annotate("5", 150000000, "G", "A")
    assert result_a["status"] == STATUS_OK
    assert result_a["fields"]["ds_acceptor_gain"] == pytest.approx(0.55)

    result_c = annotate("5", 150000000, "G", "C")
    assert result_c["status"] == STATUS_OK
    assert result_c["fields"]["ds_acceptor_gain"] == pytest.approx(0.01)


def test_full_pipeline_dot_fields_become_none_status_ok(registered_resource):
    result = annotate("7", 100000000, "C", "A")
    assert result["status"] == STATUS_OK
    assert result["fields"]["ds_acceptor_gain"] is None
    assert result["fields"]["ds_donor_gain"] is None
    assert result["fields"]["ds_acceptor_loss"] == pytest.approx(0.30)
    assert result["fields"]["max_delta_score"] == pytest.approx(0.30)


def test_full_pipeline_intronic_high_ds_ag(registered_resource):
    result = annotate("2", 179415121, "G", "C")
    assert result["status"] == STATUS_OK
    assert result["fields"]["ds_acceptor_gain"] == pytest.approx(0.87)
    assert result["fields"]["max_delta_score"] == pytest.approx(0.87)


def test_chromosome_naming_passthrough(registered_resource):
    # Canonical input "17" matches the fixture row "17" directly.
    result = annotate("17", 41276045, "G", "T")
    assert result["status"] == STATUS_OK


def test_missing_resource_raises_unknown_resource_error():
    # No registered_resource fixture — fake manager has no resource set.
    with pytest.raises(UnknownResourceError):
        annotate("17", 41276045, "G", "T")


def test_corrupted_resource_propagates_not_downgraded(registered_resource_error):
    registered_resource_error(ResourceCorruptedError("simulated corruption"))
    with pytest.raises(ResourceCorruptedError):
        annotate("17", 41276045, "G", "T")


def test_invalid_chrom_raises_validation_error(registered_resource):
    with pytest.raises(ValidationError):
        annotate("not_a_chrom", 100, "A", "T")


def test_indel_raises_validation_error(registered_resource):
    with pytest.raises(ValidationError):
        annotate("1", 100, "AT", "T")


def test_unpinned_version_raises_validation_error(registered_resource, monkeypatch):
    import modules.spliceai.annotator as ann_mod
    from pathlib import Path

    class NullVersionConfig:
        cache_dir = Path("/tmp")

        def version(self, key):
            return None

    monkeypatch.setattr(ann_mod, "get_config", lambda: NullVersionConfig())
    with pytest.raises(ValidationError, match="spliceai_version"):
        annotate("17", 41276045, "G", "T")


def test_envelope_fields_are_complete(registered_resource):
    result = annotate("17", 41276045, "G", "T")
    fields = result["fields"]
    expected_keys = {
        "ds_acceptor_gain", "ds_acceptor_loss", "ds_donor_gain", "ds_donor_loss",
        "dp_acceptor_gain", "dp_acceptor_loss", "dp_donor_gain", "dp_donor_loss",
        "max_delta_score", "gene_symbol",
        "source_dataset", "data_release", "annotation_source",
    }
    assert expected_keys.issubset(fields.keys())


def test_source_metadata_correct(registered_resource):
    result = annotate("17", 41276045, "G", "T")
    fields = result["fields"]
    assert fields["source_dataset"] == "spliceai_masked_snv"
    assert fields["annotation_source"] == "local"
    assert fields["data_release"] == "spliceai:fixture-v1"
    assert result["source_version"] == "spliceai:fixture-v1"