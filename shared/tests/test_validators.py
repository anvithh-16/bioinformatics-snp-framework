import pytest
from shared.validators import validate_variant, validate_chrom, validate_position, validate_allele
from shared.exceptions import ValidationError


def test_validate_variant_happy_path():
    v = validate_variant("1", 12345, "A", "G")
    assert v.chrom == "1"
    assert v.position == 12345
    assert v.reference == "A"
    assert v.alternate == "G"
    assert v.variant_id == "1:12345:A:G"


def test_chr_prefix_stripped():
    assert validate_chrom("chr1") == "1"
    assert validate_chrom("chrX") == "X"
    assert validate_chrom("chrM") == "MT"


def test_invalid_chrom_rejected():
    with pytest.raises(ValidationError):
        validate_chrom("26")


def test_invalid_position_rejected():
    with pytest.raises(ValidationError):
        validate_position(-5)
    with pytest.raises(ValidationError):
        validate_position("not_a_number")


def test_invalid_allele_rejected():
    with pytest.raises(ValidationError):
        validate_allele("<DEL>", field_name="alternate")
    with pytest.raises(ValidationError):
        validate_allele("", field_name="reference")


def test_indel_allele_accepted():
    assert validate_allele("ACGT", field_name="reference") == "ACGT"


def test_non_grch38_build_rejected():
    with pytest.raises(ValidationError):
        validate_variant("1", 100, "A", "G", genome_build="GRCh37")
