from __future__ import annotations

"""
Pure-function parser tests against small synthetic INFO-string fixtures.
No file I/O, no fixtures, no framework dependencies — just the parser
functions in isolation. Mirrors gnomAD's parser.py test separation.
"""

import pytest

from modules.spliceai.parser import (
    _extract_spliceai_info_value,
    _parse_delta_position,
    _parse_delta_score,
    _parse_entry,
    parse_variant_rows,
)


# ---------------------------------------------------------------------------
# _parse_entry
# ---------------------------------------------------------------------------

def test_parse_entry_full_valid_entry():
    entry = "T|BRCA1|0.02|0.91|0.01|0.03|-2|3|1|-4"
    result = _parse_entry(entry)
    assert result is not None
    assert result["allele"] == "T"
    assert result["symbol"] == "BRCA1"
    assert result["ds_ag"] == pytest.approx(0.02)
    assert result["ds_al"] == pytest.approx(0.91)
    assert result["ds_dg"] == pytest.approx(0.01)
    assert result["ds_dl"] == pytest.approx(0.03)
    assert result["dp_ag"] == -2
    assert result["dp_al"] == 3
    assert result["dp_dg"] == 1
    assert result["dp_dl"] == -4


def test_parse_entry_dot_fields_become_none():
    entry = "A|GENE|.|0.30|.|0.10|.|5|.|2"
    result = _parse_entry(entry)
    assert result is not None
    assert result["ds_ag"] is None
    assert result["ds_dg"] is None
    assert result["dp_ag"] is None
    assert result["dp_dg"] is None
    assert result["ds_al"] == pytest.approx(0.30)
    assert result["dp_al"] == 5


def test_parse_entry_allele_is_uppercased():
    entry = "t|GENE|0.1|0.2|0.3|0.4|1|2|3|4"
    result = _parse_entry(entry)
    assert result["allele"] == "T"


def test_parse_entry_wrong_field_count_returns_none():
    assert _parse_entry("T|BRCA1|0.02|0.91") is None


def test_parse_entry_dot_symbol_becomes_none():
    entry = "T|.|0.1|0.2|0.3|0.4|1|2|3|4"
    result = _parse_entry(entry)
    assert result["symbol"] is None


# ---------------------------------------------------------------------------
# parse_variant_rows — exhaustive edge-case coverage
# ---------------------------------------------------------------------------

def _vcf_row(info, chrom="1", pos="100", ref="A", alt="T"):
    return (chrom, pos, ".", ref, alt, ".", ".", info)


def test_parse_variant_rows_empty_list_returns_none():
    assert parse_variant_rows([], "T") is None


def test_parse_variant_rows_position_scored_only_for_other_allele():
    # Position exists in the file for allele C but query is for T -> no_data
    info = "SpliceAI=C|GENE|0.5|0.1|0.2|0.3|1|2|3|4"
    assert parse_variant_rows([_vcf_row(info)], "T") is None


def test_parse_variant_rows_returns_first_matching_entry_across_rows():
    # Two rows at the same position (tabix can return multiple rows).
    # The first row has the matching allele; the second has a different one.
    info1 = "SpliceAI=T|GENE|0.9|0.1|0.1|0.1|1|2|3|4"
    info2 = "SpliceAI=C|GENE|0.0|0.0|0.0|0.0|0|0|0|0"
    rows = [_vcf_row(info1), _vcf_row(info2)]
    result = parse_variant_rows(rows, "T")
    assert result is not None
    assert result["ds_ag"] == pytest.approx(0.9)


def test_parse_variant_rows_multi_allele_comma_separated():
    info = "SpliceAI=A|G1|0.55|0.10|0.02|0.03|5|-2|1|-3,C|G2|0.01|0.02|0.03|0.01|1|2|3|4"
    row = _vcf_row(info, alt="A,C")
    # Query for second allele
    result = parse_variant_rows([row], "C")
    assert result is not None
    assert result["symbol"] == "G2"
    assert result["ds_ag"] == pytest.approx(0.01)


def test_parse_variant_rows_skips_malformed_entries_tries_others():
    # First entry malformed (wrong field count), second is valid match.
    info = "SpliceAI=T|GENE|0.9,A|GENE2|0.1|0.2|0.3|0.4|1|2|3|4"
    row = _vcf_row(info, alt="T,A")
    result = parse_variant_rows([row], "A")
    assert result is not None
    assert result["symbol"] == "GENE2"


def test_parse_variant_rows_no_spliceai_key_in_info_returns_none():
    row = _vcf_row("AF=0.01;END=100")
    assert parse_variant_rows([row], "T") is None


def test_parse_variant_rows_semicolon_before_spliceai():
    info = "SOMEFLAG;SpliceAI=T|GENE|0.7|0.2|0.1|0.05|-1|2|3|4"
    result = parse_variant_rows([_vcf_row(info)], "T")
    assert result is not None
    assert result["ds_ag"] == pytest.approx(0.7)


def test_parse_variant_rows_semicolon_after_spliceai():
    info = "SpliceAI=T|GENE|0.7|0.2|0.1|0.05|-1|2|3|4;SOMEOTHER=X"
    result = parse_variant_rows([_vcf_row(info)], "T")
    assert result is not None
    assert result["ds_ag"] == pytest.approx(0.7)