from __future__ import annotations

import pytest

from shared.exceptions import ResourceCorruptedError, UnknownResourceError

from modules.alphamissense.annotator import annotate
from modules.alphamissense.constants import (
    STATUS_MULTIPLE_MATCHES,
    STATUS_NO_DATA,
    STATUS_OK,
)


def test_full_pipeline_ok_status(registered_resource):
    result = annotate("17", 7674220, "C", "T")
    assert result["status"] == STATUS_OK
    assert result["variant_id"] == "17:7674220:C:T"
    assert result["module_name"] == "alphamissense"
    assert result["fields"]["am_pathogenicity"] == pytest.approx(0.9938)
    assert result["fields"]["am_class"] == "likely_pathogenic"
    assert result["fields"]["transcript_id"] == "ENST00000269305.9"
    assert result["fields"]["match_count"] == 1


def test_full_pipeline_no_data_status(registered_resource):
    result = annotate("1", 1, "A", "T")
    assert result["status"] == STATUS_NO_DATA
    assert result["fields"]["am_pathogenicity"] is None
    assert result["fields"]["match_count"] == 0


def test_full_pipeline_multiple_matches_status(registered_resource):
    result = annotate("5", 5000000, "G", "T")
    assert result["status"] == STATUS_MULTIPLE_MATCHES
    assert result["fields"]["match_count"] == 2
    assert result["fields"]["am_pathogenicity"] is None
    assert len(result["fields"]["candidate_matches"]) == 2


def test_full_pipeline_filters_other_allele_at_same_position(registered_resource):
    # chr1:1000000 has both A>G (ambiguous) and A>C (likely_benign) in the
    # fixture. Querying for A>G must not be contaminated by the A>C row.
    result = annotate("1", 1000000, "A", "G")
    assert result["status"] == STATUS_OK
    assert result["fields"]["am_class"] == "ambiguous"
    assert result["fields"]["protein_variant"] == "K1E"


def test_chromosome_naming_is_translated_transparently(registered_resource):
    # Canonical input uses bare "17"; the underlying file uses "chr17".
    # The caller should never need to know about this translation.
    result = annotate("17", 7674220, "C", "T")
    assert result["status"] == STATUS_OK


def test_missing_resource_raises_unknown_resource_error_not_swallowed():
    # No registered_resource fixture used here -- resource is genuinely unregistered.
    with pytest.raises(UnknownResourceError):
        annotate("17", 7674220, "C", "T")


def test_corrupted_resource_propagates_not_downgraded_to_no_data(registered_resource_error):
    registered_resource_error(ResourceCorruptedError("simulated corruption"))
    with pytest.raises(ResourceCorruptedError):
        annotate("17", 7674220, "C", "T")


def test_invalid_input_raises_validation_error_before_any_lookup(registered_resource):
    from shared.exceptions import ValidationError

    with pytest.raises(ValidationError):
        annotate("not_a_real_chrom", 100, "A", "T")

    with pytest.raises(ValidationError):
        annotate("1", 100, "AT", "T")  # not a SNV