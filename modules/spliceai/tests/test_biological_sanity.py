from __future__ import annotations

"""
Biological sanity checks, per the frozen design (Section 16).

IMPORTANT CAVEAT: this sandbox has no access to the real SpliceAI masked
SNV file. These tests run against the synthetic fixture defined in
conftest.py, which encodes the *expected direction* of each well-known
variant's classification, not values read from the real Illumina file.
They confirm the pipeline produces the right status/shape/sign for known
cases — they do NOT, by themselves, constitute validation against the
real dataset.

Before trusting these as genuine biological sanity checks, re-run this
file against the real pinned file in your environment. If any directional
expectation fails against the real data, that is a finding worth
investigating, not a reason to edit the test to match.
"""

import pytest

from modules.spliceai.annotator import annotate
from modules.spliceai.constants import STATUS_NO_DATA, STATUS_OK


def test_canonical_splice_donor_disruption_has_high_ds_al(registered_resource):
    """
    A well-characterised canonical donor-site disruption (synthetic BRCA1
    exon 10 donor, chr17:41276045 G>T in the fixture) should yield a high
    DS_AL (acceptor loss) or DS_DL (donor loss) score. The fixture encodes
    DS_AL=0.91, which is above the commonly-cited 0.5 threshold for
    clinical relevance.

    If this fails against the real file, the coordinate or allele has
    shifted in the version you downloaded — investigate before dismissing.
    """
    result = annotate("17", 41276045, "G", "T")
    assert result["status"] == STATUS_OK
    assert result["fields"]["max_delta_score"] > 0.5
    # Specifically the fixture encodes donor/acceptor loss as the dominant
    # signal; at minimum one of the loss scores must be elevated.
    ds_al = result["fields"]["ds_acceptor_loss"]
    ds_dl = result["fields"]["ds_donor_loss"]
    assert ds_al is not None or ds_dl is not None
    dominant = max(v for v in (ds_al, ds_dl) if v is not None)
    assert dominant > 0.5


def test_synonymous_exonic_variant_has_low_max_delta_score(registered_resource):
    """
    A synonymous exonic variant with no known splicing effect (synthetic
    OR4F5, chr1:69511 A>T) should return a low max_delta_score,
    demonstrating the module correctly returns low scores for
    consequence-class-benign variants rather than uniformly high scores
    near gene structure.
    """
    result = annotate("1", 69511, "A", "T")
    assert result["status"] == STATUS_OK
    assert result["fields"]["max_delta_score"] is not None
    assert result["fields"]["max_delta_score"] < 0.2


def test_deep_intronic_cryptic_acceptor_gain_has_high_ds_ag(registered_resource):
    """
    A deep intronic variant known to create a cryptic splice acceptor
    (synthetic SCN1A, chr2:179415121 G>C) should score high on DS_AG
    (acceptor gain) specifically. This is the canonical SpliceAI use case:
    a variant VEP's consequence-class would not flag, which SpliceAI
    detects via its learned model.

    DS_AG > 0.5 is the fixture-encoded expectation. If the real file
    returns a different score for this coordinate, that is a genuine
    finding about the specific variant, not a bug.
    """
    result = annotate("2", 179415121, "G", "C")
    assert result["status"] == STATUS_OK
    assert result["fields"]["ds_acceptor_gain"] is not None
    assert result["fields"]["ds_acceptor_gain"] > 0.5


def test_position_outside_scored_window_is_no_data_not_zero(registered_resource):
    """
    A variant outside Illumina's scored window (>5kb from any annotated
    gene boundary) must return status='no_data', not status='ok' with
    zeroed scores. 'Not scored' ≠ 'zero splicing impact' — this is the
    same principle as gnomAD's 'not observed ≠ frequency zero'.

    Uses a position not present in the fixture (far from any fixture entry)
    to exercise the no-rows path cleanly.
    """
    result = annotate("1", 999999999, "A", "T")
    assert result["status"] == STATUS_NO_DATA
    assert result["fields"]["max_delta_score"] is None
    assert result["fields"]["ds_acceptor_gain"] is None


def test_gene_symbol_is_present_for_scored_variant(registered_resource):
    """
    Every status='ok' result must carry a gene_symbol (Illumina's own
    gene association) — it must not be silently dropped by the parser.
    """
    result = annotate("17", 41276045, "G", "T")
    assert result["status"] == STATUS_OK
    assert result["fields"]["gene_symbol"] is not None
    assert result["fields"]["gene_symbol"] == "BRCA1"


def test_source_metadata_is_present_in_every_envelope(registered_resource):
    """
    Provenance fields must survive end-to-end: source_dataset,
    annotation_source, and data_release (= pinned version) must all be
    present and non-None in every status='ok' envelope.
    """
    result = annotate("17", 41276045, "G", "T")
    fields = result["fields"]
    assert fields["source_dataset"] == "spliceai_masked_snv"
    assert fields["annotation_source"] == "local"
    assert fields["data_release"] is not None
    assert result["source_version"] == fields["data_release"]