import pytest

from shared.exceptions import ValidationError
from shared.validators import validate_variant

from modules.vep.constants import GENOMIC_REGION_DEFAULT, GENOMIC_REGION_MAP
from modules.vep.parser import map_genomic_region, parse_vep_record, select_transcript

from .conftest import load_fixture


# ---------------------------------------------------------------------------
# Input validation (delegated to shared.validators, exercised through the
# variant shapes this module actually receives)
# ---------------------------------------------------------------------------

def test_validate_variant_invalid_chrom():
    with pytest.raises(ValidationError):
        validate_variant("chr99", 1000, "A", "G")


def test_validate_variant_invalid_position_zero():
    with pytest.raises(ValidationError):
        validate_variant("1", 0, "A", "G")


def test_validate_variant_invalid_position_negative():
    with pytest.raises(ValidationError):
        validate_variant("1", -5, "A", "G")


def test_validate_variant_invalid_allele():
    with pytest.raises(ValidationError):
        validate_variant("1", 1000000, "A", "<DEL>")


def test_validate_variant_mt_chromosome():
    v = validate_variant("MT", 1555, "A", "G")
    assert v.chrom == "MT"


def test_validate_variant_x_chromosome():
    v = validate_variant("X", 154000000, "A", "G")
    assert v.chrom == "X"


# ---------------------------------------------------------------------------
# genomic_region mapping
# ---------------------------------------------------------------------------

def test_genomic_region_map_completeness():
    for so_term, region in GENOMIC_REGION_MAP.items():
        assert isinstance(region, str) and region


def test_genomic_region_fallback_for_unknown_term():
    assert map_genomic_region("some_unmapped_so_term") == GENOMIC_REGION_DEFAULT


def test_genomic_region_fallback_for_none():
    assert map_genomic_region(None) == GENOMIC_REGION_DEFAULT


def test_utr_split_into_distinct_regions():
    five_prime = map_genomic_region("5_prime_utr_variant")
    three_prime = map_genomic_region("3_prime_utr_variant")
    assert five_prime != three_prime
    assert "5' UTR" in five_prime
    assert "3' UTR" in three_prime


# ---------------------------------------------------------------------------
# Transcript selection policy (3A Part 5.2)
# ---------------------------------------------------------------------------

def test_transcript_selection_mane_select():
    record = load_fixture("vep_response_hbb.json")[0]
    tx, source = select_transcript(
        record["transcript_consequences"], variant_id="11:5227002:T:A"
    )
    assert source == "mane_select"
    assert tx["transcript_id"] == "ENST00000647020"


def test_transcript_selection_canonical_fallback():
    record = load_fixture("vep_response_canonical_fallback.json")[0]
    tx, source = select_transcript(
        record["transcript_consequences"], variant_id="19:11089875:T:G"
    )
    assert source == "ensembl_canonical"
    assert tx["transcript_id"] == "ENST00000252444"


def test_transcript_selection_index0_fallback(caplog):
    transcripts = [
        {"transcript_id": "ENST_A", "gene_symbol": "FOO"},
        {"transcript_id": "ENST_B", "gene_symbol": "FOO"},
    ]
    tx, source = select_transcript(transcripts, variant_id="1:1:A:G")
    assert source == "fallback"
    assert tx["transcript_id"] == "ENST_A"


def test_transcript_selection_empty_list():
    tx, source = select_transcript([], variant_id="1:1:A:G")
    assert tx is None


# ---------------------------------------------------------------------------
# Full record parsing
# ---------------------------------------------------------------------------

def test_full_response_parsing_hbb():
    record = load_fixture("vep_response_hbb.json")[0]
    variant = validate_variant("11", 5227002, "T", "A")
    annotation = parse_vep_record(record, variant=variant, ensembl_release="113")

    assert annotation.variant_id == "11:5227002:T:A"
    assert annotation.gene_symbol == "HBB"
    assert annotation.gene_id == "ENSG00000244734"
    assert annotation.most_severe_consequence == "missense_variant"
    assert annotation.impact == "MODERATE"
    assert annotation.genomic_region == "Coding Exon"
    assert annotation.transcript_id == "ENST00000647020"
    assert annotation.transcript_source == "mane_select"
    assert annotation.transcript_count == 2
    assert annotation.hgvs_c == "ENST00000647020.1:c.20A>T"
    assert annotation.hgvs_p == "ENSP00000496200.1:p.Glu7Val"
    assert annotation.amino_acid_change == "E/V"
    assert annotation.codon_change == "gAg/gTg"
    assert annotation.exon_number == "1/3"
    assert annotation.ensembl_release == "113"
    assert annotation.status == "ok"
    # Suppressed fields must never appear as VEPAnnotation attributes.
    assert not hasattr(annotation, "polyphen_score")
    assert not hasattr(annotation, "sift_score")


def test_partial_response_parsing_missing_hgvs():
    record = {
        "most_severe_consequence": "intron_variant",
        "transcript_consequences": [
            {
                "transcript_id": "ENST00000999999",
                "gene_id": "ENSG00000999999",
                "gene_symbol": "FAKE1",
                "biotype": "protein_coding",
                "canonical": 1,
                # no hgvsc / hgvsp / amino_acids keys at all
            }
        ],
    }
    variant = validate_variant("1", 100, "A", "G")
    annotation = parse_vep_record(record, variant=variant, ensembl_release="113")

    assert annotation.hgvs_c is None
    assert annotation.hgvs_p is None
    assert annotation.amino_acid_change is None
    assert annotation.genomic_region == "Intron"


def test_missing_fields_are_none_not_string_none():
    record = {
        "most_severe_consequence": "missense_variant",
        "transcript_consequences": [
            {
                "transcript_id": "ENST1",
                "gene_id": "ENSG1",
                "gene_symbol": "FOO",
                "mane_select": "NM_1",
                "amino_acids": "None",  # the prototype's literal bug
            }
        ],
    }
    variant = validate_variant("1", 100, "A", "G")
    annotation = parse_vep_record(record, variant=variant, ensembl_release="113")
    assert annotation.amino_acid_change is None
    assert annotation.amino_acid_change != "None"


def test_intergenic_record_has_no_gene_but_transcript_count_zero():
    record = {
        "most_severe_consequence": "intergenic_variant",
        "transcript_consequences": [],
    }
    variant = validate_variant("8", 144500000, "A", "G")
    annotation = parse_vep_record(record, variant=variant, ensembl_release="113")
    assert annotation.gene_symbol is None
    assert annotation.transcript_count == 0
    assert annotation.transcript_source is None
    assert annotation.genomic_region == "Non-Coding / Intergenic"


def test_variant_id_uses_colon_separator():
    variant = validate_variant("11", 5227002, "T", "A")
    assert variant.variant_id == "11:5227002:T:A"
    assert "-" not in variant.variant_id