from __future__ import annotations

"""
Mocked lookup tests: use the small local fixture VCF + .tbi built by
conftest.write_fixture_vcf(). No network required; exercises the full
annotate() -> client -> tabix -> parser -> model -> envelope path against
a real bgzip+tabix file, with the reference manager and config faked.
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
    # chr17:41276045 is scored for G->T only; querying G->C should be no_data.
    result = annotate("17", 41276045, "G", "C")
    assert result["status"] == STATUS_NO_DATA


def test_full_pipeline_multi_allele_selects_correct_entry(registered_resource):
    # chr5:150000000 has A and C entries; query for A.
    result_a = annotate("5", 150000000, "G", "A")
    assert result_a["status"] == STATUS_OK
    assert result_a["fields"]["ds_acceptor_gain"] == pytest.approx(0.55)

    # Query for C at same position.
    result_c = annotate("5", 150000000, "G", "C")
    assert result_c["status"] == STATUS_OK
    assert result_c["fields"]["ds_acceptor_gain"] == pytest.approx(0.01)


def test_full_pipeline_dot_fields_become_none_status_ok(registered_resource):
    result = annotate("7", 100000000, "C", "A")
    assert result["status"] == STATUS_OK
    assert result["fields"]["ds_acceptor_gain"] is None
    assert result["fields"]["ds_donor_gain"] is None
    assert result["fields"]["ds_acceptor_loss"] == pytest.approx(0.30)
    # max_delta_score is derived from non-None values only.
    assert result["fields"]["max_delta_score"] == pytest.approx(0.30)


def test_full_pipeline_intronic_high_ds_ag(registered_resource):
    result = annotate("2", 179415121, "G", "C")
    assert result["status"] == STATUS_OK
    assert result["fields"]["ds_acceptor_gain"] == pytest.approx(0.87)
    assert result["fields"]["max_delta_score"] == pytest.approx(0.87)


def test_chromosome_naming_translated_transparently(registered_resource):
    # Caller uses bare "17"; the underlying file uses "chr17".
    result = annotate("17", 41276045, "G", "T")
    assert result["status"] == STATUS_OK


def test_missing_resource_raises_unknown_resource_error(fake_reference_manager):
    # No resource registered — fake_reference_manager has no resource set.
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


def test_unpinned_version_raises_validation_error(
    registered_resource, monkeypatch
):
    import modules.spliceai.annotator as ann_mod

    class NullVersionConfig:
        cache_dir = registered_resource.path  # unused but must exist

        def version(self, key):
            return None

    monkeypatch.setattr(ann_mod, "get_config", lambda: NullVersionConfig())
    with pytest.raises(ValidationError, match="spliceai_version"):
        annotate("17", 41276045, "G", "T")