from __future__ import annotations

import pytest

from shared.exceptions import ValidationError

from modules.alphamissense.constants import (
    STATUS_MULTIPLE_MATCHES,
    STATUS_NO_DATA,
    STATUS_OK,
)
from modules.alphamissense.models import AlphaMissenseAnnotation, AlphaMissenseCandidate
from modules.alphamissense.parser import (
    normalize_chrom_for_file,
    normalize_chrom_from_file,
    parse_matching_rows,
    parse_row,
)

ROW_OK = ("chr17", "7674220", "C", "T", "hg38", "P04637", "ENST00000269305.9", "R175H", "0.9938", "likely_pathogenic")


# ---------------------------------------------------------------------------
# chromosome normalization
# ---------------------------------------------------------------------------

def test_normalize_chrom_for_file_adds_prefix():
    assert normalize_chrom_for_file("17") == "chr17"
    assert normalize_chrom_for_file("X") == "chrX"


def test_normalize_chrom_for_file_is_idempotent():
    assert normalize_chrom_for_file("chr17") == "chr17"


def test_normalize_chrom_from_file_strips_prefix():
    assert normalize_chrom_from_file("chr17") == "17"
    assert normalize_chrom_from_file("chrX") == "X"


def test_normalize_chrom_from_file_is_idempotent():
    assert normalize_chrom_from_file("17") == "17"


# ---------------------------------------------------------------------------
# row parsing
# ---------------------------------------------------------------------------

def test_parse_row_happy_path():
    candidate = parse_row(ROW_OK)
    assert candidate.transcript_id == "ENST00000269305.9"
    assert candidate.uniprot_id == "P04637"
    assert candidate.protein_variant == "R175H"
    assert candidate.am_pathogenicity == pytest.approx(0.9938)
    assert candidate.am_class == "likely_pathogenic"


def test_parse_row_wrong_column_count_raises():
    with pytest.raises(ValueError):
        parse_row(("chr17", "7674220", "C", "T"))


def test_parse_row_empty_fields_become_none():
    row = ("chr1", "100", "A", "T", "hg38", "", ".", "", "", "")
    candidate = parse_row(row)
    assert candidate.uniprot_id is None
    assert candidate.transcript_id is None
    assert candidate.protein_variant is None
    assert candidate.am_pathogenicity is None
    assert candidate.am_class is None


def test_parse_row_unparseable_pathogenicity_becomes_none_not_error():
    row = ("chr1", "100", "A", "T", "hg38", "P1", "ENST1", "X1Y", "not_a_float", "likely_benign")
    candidate = parse_row(row)
    assert candidate.am_pathogenicity is None


def test_parse_row_unknown_am_class_passed_through():
    row = ("chr1", "100", "A", "T", "hg38", "P1", "ENST1", "X1Y", "0.5", "some_future_category")
    candidate = parse_row(row)
    assert candidate.am_class == "some_future_category"


# ---------------------------------------------------------------------------
# allele filtering
# ---------------------------------------------------------------------------

def test_parse_matching_rows_filters_by_exact_allele():
    rows = [
        ("chr1", "1000000", "A", "G", "hg38", "P1", "ENST1", "K1E", "0.5", "ambiguous"),
        ("chr1", "1000000", "A", "C", "hg38", "P2", "ENST2", "K1Q", "0.1", "likely_benign"),
    ]
    candidates = parse_matching_rows(rows, reference="A", alternate="G")
    assert len(candidates) == 1
    assert candidates[0].protein_variant == "K1E"


def test_parse_matching_rows_is_case_insensitive_on_alleles():
    rows = [("chr1", "100", "a", "g", "hg38", "P1", "ENST1", "K1E", "0.5", "ambiguous")]
    candidates = parse_matching_rows(rows, reference="A", alternate="G")
    assert len(candidates) == 1


def test_parse_matching_rows_returns_empty_when_no_allele_matches():
    rows = [("chr1", "100", "A", "T", "hg38", "P1", "ENST1", "K1L", "0.5", "ambiguous")]
    candidates = parse_matching_rows(rows, reference="A", alternate="G")
    assert candidates == []


def test_parse_matching_rows_keeps_genuine_multi_transcript_collision():
    rows = [
        ("chr5", "5000000", "G", "T", "hg38", "Q1", "ENST1", "V10L", "0.7", "likely_pathogenic"),
        ("chr5", "5000000", "G", "T", "hg38", "Q2", "ENST2", "M20I", "0.3", "likely_benign"),
    ]
    candidates = parse_matching_rows(rows, reference="G", alternate="T")
    assert len(candidates) == 2


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

def test_annotation_no_data_status_and_shape():
    ann = AlphaMissenseAnnotation.no_data("1:100:A:T", data_release="zenodo:x")
    assert ann.status == STATUS_NO_DATA
    assert ann.match_count == 0
    assert ann.am_pathogenicity is None
    assert ann.candidate_matches is None


def test_annotation_single_match_status_and_shape():
    candidate = AlphaMissenseCandidate(
        transcript_id="ENST1", uniprot_id="P1", protein_variant="R175H",
        am_pathogenicity=0.99, am_class="likely_pathogenic",
    )
    ann = AlphaMissenseAnnotation.single_match("17:7674220:C:T", candidate, data_release="zenodo:x")
    assert ann.status == STATUS_OK
    assert ann.match_count == 1
    assert ann.am_pathogenicity == 0.99
    assert ann.am_class == "likely_pathogenic"
    assert ann.candidate_matches is None


def test_annotation_multiple_matches_preserves_all_candidates_none_dropped():
    candidates = [
        AlphaMissenseCandidate("ENST1", "Q1", "V10L", 0.7, "likely_pathogenic"),
        AlphaMissenseCandidate("ENST2", "Q2", "M20I", 0.3, "likely_benign"),
    ]
    ann = AlphaMissenseAnnotation.multiple_matches("5:5000000:G:T", candidates, data_release="zenodo:x")
    assert ann.status == STATUS_MULTIPLE_MATCHES
    assert ann.match_count == 2
    assert ann.am_pathogenicity is None  # never arbitrarily pick one
    assert len(ann.candidate_matches) == 2
    assert {c["transcript_id"] for c in ann.candidate_matches} == {"ENST1", "ENST2"}


def test_annotation_to_envelope_shape():
    ann = AlphaMissenseAnnotation.no_data("1:100:A:T", data_release="zenodo:x")
    envelope = ann.to_envelope()
    assert envelope["variant_id"] == "1:100:A:T"
    assert envelope["module_name"] == "alphamissense"
    assert envelope["status"] == STATUS_NO_DATA
    assert envelope["source_version"] == "zenodo:x"
    assert "fields" in envelope
    assert envelope["fields"]["source_dataset"] == "AlphaMissense_hg38"
    assert envelope["fields"]["annotation_source"] == "alphamissense_local_tabix"