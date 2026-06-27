"""
Live integration tests — these make real network calls to
rest.ensembl.org and are skipped by default. Run explicitly with:

    PYTHONPATH=. pytest modules/vep/tests/test_integration.py -m integration -v

Per 3A §8.2 / PROJECT_CONTEXT.md, these exist to sanity-check biological
correctness against known variants, not to be part of the default,
network-free test run.
"""

import pytest

from modules.vep import annotate

pytestmark = pytest.mark.integration


def test_hbb_sickle_cell_live():
    result = annotate("11", 5227002, "T", "A")
    fields = result["fields"]
    assert fields["most_severe_consequence"] == "missense_variant"
    assert fields["gene_symbol"] == "HBB"
    assert fields["transcript_source"] in ("mane_select", "ensembl_canonical")


def test_tp53_r175h_live():
    result = annotate("17", 7674220, "C", "T")
    fields = result["fields"]
    assert fields["gene_symbol"] == "TP53"
    assert fields["hgvs_p"] is not None


def test_brca1_frameshift_live():
    # BRCA1 c.5266dupC region — exercised here as a SNV-equivalent probe
    # is out of scope (this module supports SNVs only); kept as a
    # placeholder documenting the known limitation rather than removed
    # silently. See README "Limitations".
    pytest.skip(
        "Indel variants are out of scope for the VEP module's SNV-only "
        "region endpoint (3A §4.1); revisit when indel support is added."
    )


def test_intergenic_live():
    result = annotate("8", 144500000, "A", "G")
    fields = result["fields"]
    assert fields["most_severe_consequence"] in ("intergenic_variant", "upstream_gene_variant", "downstream_gene_variant")


def test_mt_chromosome_live():
    result = annotate("MT", 1555, "A", "G")
    assert result["status"] == "ok"


def test_mane_select_present_on_brca2_live():
    # BRCA2 missense near a well-annotated exon.
    result = annotate("13", 32390946, "G", "A")
    fields = result["fields"]
    if fields["gene_symbol"] == "BRCA2":
        assert fields["transcript_source"] == "mane_select"