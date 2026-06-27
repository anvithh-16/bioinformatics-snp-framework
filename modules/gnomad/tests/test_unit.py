"""
modules/gnomad/tests/test_unit.py

Pure unit tests for the parsing/combination logic in parser.py and the
variant-id conversion helper in __init__.py. No network calls of any
kind are made here — these tests exercise plain Python functions against
in-memory dicts (loaded from the same JSON fixtures the mocked-client
tests use), per the requirement that "the GraphQL API must never be
called during unit tests."
"""

import json
from pathlib import Path

import pytest

from modules.gnomad.parser import parse_variant_response
from modules.gnomad import _to_gnomad_variant_id
from modules.gnomad.constants import STATUS_LOW_CONFIDENCE, STATUS_NO_DATA, STATUS_OK

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class TestVariantIdConversion:
    def test_basic_conversion(self):
        assert _to_gnomad_variant_id("1", 55051215, "G", "A") == "1-55051215-G-A"

    def test_strips_chr_prefix(self):
        assert _to_gnomad_variant_id("chr1", 55051215, "G", "A") == "1-55051215-G-A"

    def test_strips_chr_prefix_case_insensitive(self):
        assert _to_gnomad_variant_id("CHR1", 100, "A", "T") == "1-100-A-T"


class TestParseVariantResponse:
    def test_found_variant_combines_exome_and_genome(self):
        raw = _load_fixture("gnomad_response_found.json")["data"]["variant"]
        fields = parse_variant_response(raw, "1-55051215-G-A", "gnomad_r4")

        # ac_overall/an_overall must be the SUM of exome+genome, not either
        # subset alone and not an average of the two af values.
        assert fields["ac_overall"] == 12 + 4
        assert fields["an_overall"] == 291248 + 76480
        expected_af = (12 + 4) / (291248 + 76480)
        assert fields["af_overall"] == pytest.approx(expected_af)
        assert fields["status"] == STATUS_OK
        assert fields["filter_status"] == "PASS"
        assert fields["n_homozygotes"] == 0
        assert fields["annotation_source"] == "remote"

    def test_found_variant_population_frequencies_combined(self):
        raw = _load_fixture("gnomad_response_found.json")["data"]["variant"]
        fields = parse_variant_response(raw, "1-55051215-G-A", "gnomad_r4")

        pops = fields["population_frequencies"]
        assert "afr" in pops and "nfe" in pops
        # afr: ac 2+2=4, an 16240+13000=29240
        assert pops["afr"]["ac"] == 4
        assert pops["afr"]["an"] == 16240 + 13000

    def test_found_variant_popmax_is_highest_population_af(self):
        raw = _load_fixture("gnomad_response_found.json")["data"]["variant"]
        fields = parse_variant_response(raw, "1-55051215-G-A", "gnomad_r4")

        pops = fields["population_frequencies"]
        expected_pop = max(pops.items(), key=lambda kv: kv[1]["af"])[0]
        assert fields["popmax_population"] == expected_pop
        assert fields["af_popmax"] == pytest.approx(pops[expected_pop]["af"])

    def test_not_found_variant_returns_no_data_status(self):
        fields = parse_variant_response(None, "99-1-A-T", "gnomad_r4")

        assert fields["status"] == STATUS_NO_DATA
        assert fields["af_overall"] is None
        assert fields["ac_overall"] is None
        assert fields["an_overall"] is None
        assert fields["af_popmax"] is None
        assert fields["popmax_population"] is None
        assert fields["population_frequencies"] == {}
        assert fields["filter_status"] is None
        assert fields["n_homozygotes"] is None

    def test_partial_coverage_exome_missing_does_not_crash(self):
        raw = _load_fixture("gnomad_response_partial.json")["data"]["variant"]
        fields = parse_variant_response(raw, "11-5227002-T-A", "gnomad_r4")

        # Only genome present; overall must equal genome-only values.
        assert fields["ac_overall"] == 940
        assert fields["an_overall"] == 76480
        assert fields["n_homozygotes"] == 6

    def test_non_pass_filter_yields_low_confidence_status(self):
        raw = _load_fixture("gnomad_response_partial.json")["data"]["variant"]
        fields = parse_variant_response(raw, "11-5227002-T-A", "gnomad_r4")

        assert fields["filter_status"] == "AC0"
        assert fields["status"] == STATUS_LOW_CONFIDENCE

    def test_missing_values_are_python_none_not_strings(self):
        fields = parse_variant_response(None, "99-1-A-T", "gnomad_r4")

        for key in ("af_overall", "ac_overall", "an_overall", "filter_status"):
            value = fields[key]
            assert value is None, f"{key} should be None, got {value!r}"
            assert value != "None"
            assert value != ""
            assert value != "Unknown"