"""
Biological sanity checks, per the frozen design (Conversation 4A,
section 22).

IMPORTANT CAVEAT: this sandbox has no network access to download the
real AlphaMissense_hg38.tsv.gz. These tests run against the synthetic
fixture defined in conftest.py, which encodes the *expected direction*
of each well-known variant's classification, not values read from the
real DeepMind file. They confirm the pipeline produces the right
status/shape/sign for known cases -- they do NOT, by themselves,
constitute validation of the real dataset. Re-run this file against
the real pinned file in your environment as part of bringing the
resource online; if any of these directional expectations fail
against the real data, that is a finding worth investigating, not a
reason to edit the test to match.
"""

from __future__ import annotations

from modules.alphamissense.annotator import annotate
from modules.alphamissense.constants import STATUS_OK


def test_tp53_r175h_is_likely_pathogenic(registered_resource):
    """
    TP53 R175H (17:7674220:C:T) is one of the best-characterized
    oncogenic hotspot mutations in human cancer. A correctly wired
    pipeline returning anything other than a high am_pathogenicity /
    likely_pathogenic classification for this coordinate indicates a
    bug in coordinate handling, allele filtering, or column mapping --
    not a surprising biological finding.
    """
    result = annotate("17", 7674220, "C", "T")
    assert result["status"] == STATUS_OK
    assert result["fields"]["am_class"] == "likely_pathogenic"
    assert result["fields"]["am_pathogenicity"] > 0.9


def test_apoe_e4_is_not_classed_as_likely_pathogenic(registered_resource):
    """
    APOE rs429358 (19:44908684:T:C, the epsilon-4 allele) is a common,
    clinically significant longevity/disease-risk-modifying
    polymorphism -- but it is not a classic monogenic-pathogenic
    missense variant, and a frequency-anchored model is expected to
    lean toward "benign" for it. This test exists specifically to guard
    the caveat documented in the frozen design: a "likely_benign" call
    here must never be read downstream as "this variant doesn't
    matter" for the project's eventual longevity/disease-progression
    ML goal -- it matters for a different reason than AlphaMissense's
    pathogenicity axis captures.
    """
    result = annotate("19", 44908684, "T", "C")
    assert result["status"] == STATUS_OK
    assert result["fields"]["am_class"] != "likely_pathogenic"


def test_no_known_pathogenic_classification_is_silently_dropped(registered_resource):
    """
    Cross-check that a positive control's full evidence trail survives
    end-to-end -- transcript/uniprot provenance must be present
    whenever status is "ok", not just the score.
    """
    result = annotate("17", 7674220, "C", "T")
    fields = result["fields"]
    assert fields["transcript_id"] is not None
    assert fields["uniprot_id"] is not None
    assert fields["protein_variant"] is not None