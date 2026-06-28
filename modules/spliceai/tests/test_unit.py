from __future__ import annotations

import pytest

from shared.exceptions import ValidationError

from modules.spliceai.constants import STATUS_NO_DATA, STATUS_OK
from modules.spliceai.models import SpliceAIAnnotation
from modules.spliceai.parser import (
    _extract_spliceai_info_value,
    _parse_delta_position,
    _parse_delta_score,
    normalize_chrom_for_file,
    parse_variant_rows,
)

# ---------------------------------------------------------------------------
# chromosome normalisation
# ---------------------------------------------------------------------------

def test_normalize_chrom_for_file_strips_chr_prefix():
    # The real file uses bare names; UCSC-style input must be stripped.
    assert normalize_chrom_for_file("chr17") == "17"
    assert normalize_chrom_for_file("chrX") == "X"


def test_normalize_chrom_for_file_bare_name_is_unchanged():
    # Canonical project convention already matches the file — no-op.
    assert normalize_chrom_for_file("17") == "17"
    assert normalize_chrom_for_file("X") == "X"


def test_normalize_chrom_for_file_is_case_insensitive_on_prefix():
    assert normalize_chrom_for_file("CHR17") == "17"


# ---------------------------------------------------------------------------
# scalar field parsers
# ---------------------------------------------------------------------------

def test_parse_delta_score_happy_path():
    assert _parse_delta_score("0.91") == pytest.approx(0.91)


def test_parse_delta_score_dot_is_none():
    assert _parse_delta_score(".") is None


def test_parse_delta_score_empty_is_none():
    assert _parse_delta_score("") is None


def test_parse_delta_score_unparseable_is_none_not_error():
    assert _parse_delta_score("notafloat") is None


def test_parse_delta_position_happy_path():
    assert _parse_delta_position("5") == 5
    assert _parse_delta_position("-15") == -15


def test_parse_delta_position_dot_is_none():
    assert _parse_delta_position(".") is None


def test_parse_delta_position_unparseable_is_none_not_error():
    assert _parse_delta_position("abc") is None


# ---------------------------------------------------------------------------
# INFO extraction
# ---------------------------------------------------------------------------

def test_extract_spliceai_info_value_finds_key():
    info = "AF=0.01;SpliceAI=A|BRCA1|0.91|0.01|0.02|0.03|3|-2|1|-4;END=100"
    result = _extract_spliceai_info_value(info)
    assert result == "A|BRCA1|0.91|0.01|0.02|0.03|3|-2|1|-4"


def test_extract_spliceai_info_value_missing_returns_none():
    assert _extract_spliceai_info_value("AF=0.01;END=100") is None


def test_extract_spliceai_info_value_does_not_partial_match():
    # A key like 'NotSpliceAI=...' must not match.
    assert _extract_spliceai_info_value("NotSpliceAI=A|GENE|0.1|0.2|0.3|0.4|1|2|3|4") is None


# ---------------------------------------------------------------------------
# parse_variant_rows — matching logic
# ---------------------------------------------------------------------------

def _make_row(chrom, pos, ref, alt, info):
    return (chrom, pos, ".", ref, alt, ".", ".", info)


def test_parse_variant_rows_no_rows_returns_none():
    assert parse_variant_rows([], "T") is None


def test_parse_variant_rows_matching_allele_returns_parsed():
    info = "SpliceAI=T|BRCA1|0.02|0.91|0.01|0.03|-2|3|1|-4"
    row = _make_row("17", "41276045", "G", "T", info)
    result = parse_variant_rows([row], "T")
    assert result is not None
    assert result["ds_al"] == pytest.approx(0.91)
    assert result["symbol"] == "BRCA1"
    assert result["dp_ag"] == -2


def test_parse_variant_rows_non_matching_allele_returns_none():
    info = "SpliceAI=T|BRCA1|0.02|0.91|0.01|0.03|-2|3|1|-4"
    row = _make_row("17", "41276045", "G", "T", info)
    assert parse_variant_rows([row], "C") is None


def test_parse_variant_rows_multi_allele_selects_correct_entry():
    info = "SpliceAI=A|GENEX|0.55|0.10|0.02|0.03|5|-2|1|-3,C|GENEX|0.01|0.02|0.03|0.01|1|2|3|4"
    row = _make_row("5", "150000000", "G", "A,C", info)
    # Query for A
    result_a = parse_variant_rows([row], "A")
    assert result_a is not None
    assert result_a["ds_ag"] == pytest.approx(0.55)
    # Query for C
    result_c = parse_variant_rows([row], "C")
    assert result_c is not None
    assert result_c["ds_ag"] == pytest.approx(0.01)


def test_parse_variant_rows_allele_match_is_case_insensitive():
    info = "SpliceAI=t|GENE|0.5|0.1|0.2|0.3|1|2|3|4"
    row = _make_row("1", "100", "A", "T", info)
    result = parse_variant_rows([row], "T")
    assert result is not None


def test_parse_variant_rows_dot_fields_are_none_not_no_data():
    """
    Per design Section 11 rule 6: '.' fields -> None, status stays 'ok'.
    parse_variant_rows returns a dict (not None), so the caller builds
    status='ok'.
    """
    info = "SpliceAI=A|DOTGENE|.|0.30|.|0.10|.|5|.|2"
    row = _make_row("7", "100000000", "C", "A", info)
    result = parse_variant_rows([row], "A")
    assert result is not None
    assert result["ds_ag"] is None
    assert result["ds_al"] == pytest.approx(0.30)
    assert result["ds_dg"] is None
    assert result["ds_dl"] == pytest.approx(0.10)
    assert result["dp_ag"] is None
    assert result["dp_al"] == 5
    assert result["dp_dg"] is None
    assert result["dp_dl"] == 2


def test_parse_variant_rows_row_without_spliceai_info_skipped():
    row = _make_row("1", "100", "A", "T", "AF=0.01;END=100")
    assert parse_variant_rows([row], "T") is None


def test_parse_variant_rows_short_row_skipped():
    # Row with fewer than 8 columns should be skipped, not raise.
    assert parse_variant_rows([("1", "100", ".", "A")], "T") is None


# ---------------------------------------------------------------------------
# SpliceAIAnnotation model
# ---------------------------------------------------------------------------

def test_annotation_no_data_shape():
    ann = SpliceAIAnnotation.no_data("1:100:A:T", data_release="spliceai:1.3.1")
    assert ann.status == STATUS_NO_DATA
    assert ann.ds_acceptor_gain is None
    assert ann.max_delta_score is None
    assert ann.gene_symbol is None


def test_annotation_from_parsed_computes_max_delta_score():
    ann = SpliceAIAnnotation.from_parsed(
        variant_id="17:41276045:G:T",
        data_release="spliceai:1.3.1",
        ds_ag=0.02, ds_al=0.91, ds_dg=0.01, ds_dl=0.03,
        dp_ag=-2, dp_al=3, dp_dg=1, dp_dl=-4,
        gene_symbol="BRCA1",
    )
    assert ann.status == STATUS_OK
    assert ann.max_delta_score == pytest.approx(0.91)
    assert ann.ds_acceptor_loss == pytest.approx(0.91)
    assert ann.gene_symbol == "BRCA1"


def test_annotation_max_delta_score_ignores_none_fields():
    ann = SpliceAIAnnotation.from_parsed(
        variant_id="7:100:C:A",
        data_release="spliceai:1.3.1",
        ds_ag=None, ds_al=0.30, ds_dg=None, ds_dl=0.10,
        dp_ag=None, dp_al=5, dp_dg=None, dp_dl=2,
        gene_symbol="DOTGENE",
    )
    assert ann.max_delta_score == pytest.approx(0.30)


def test_annotation_max_delta_score_is_none_when_all_ds_are_none():
    ann = SpliceAIAnnotation.from_parsed(
        variant_id="7:100:C:A",
        data_release="spliceai:1.3.1",
        ds_ag=None, ds_al=None, ds_dg=None, ds_dl=None,
        dp_ag=None, dp_al=None, dp_dg=None, dp_dl=None,
        gene_symbol=None,
    )
    assert ann.max_delta_score is None


def test_annotation_to_envelope_shape():
    ann = SpliceAIAnnotation.no_data("1:100:A:T", data_release="spliceai:1.3.1")
    envelope = ann.to_envelope()
    assert envelope["variant_id"] == "1:100:A:T"
    assert envelope["module_name"] == "spliceai"
    assert envelope["status"] == STATUS_NO_DATA
    assert envelope["source_version"] == "spliceai:1.3.1"
    assert "fields" in envelope
    assert envelope["fields"]["source_dataset"] == "spliceai_masked_snv"
    assert envelope["fields"]["annotation_source"] == "local"