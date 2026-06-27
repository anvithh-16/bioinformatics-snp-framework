"""
modules.vep.constants
======================

Frozen constants for the VEP module. Nothing here should change without
re-opening the Conversation 3A design review — these tables are part of
the frozen scientific contract (Part 6.2 and Part 10.1 of the 3A design
document).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Frozen genomic_region mapping (Conversation 3A, Part 6.2)
#
# Maps a VEP "most_severe_consequence" Sequence Ontology (SO) term onto a
# coarser structural classification used throughout the framework's ML
# feature set. 5' UTR and 3' UTR are deliberately kept separate (not
# merged into one "UTR" bucket, as the prototype did) because they have
# distinct biological significance — see 3A §6.2 for the rationale.
# ---------------------------------------------------------------------------

GENOMIC_REGION_MAP: dict[str, str] = {
    # Coding exon
    "missense_variant": "Coding Exon",
    "synonymous_variant": "Coding Exon",
    "stop_gained": "Coding Exon",
    "stop_lost": "Coding Exon",
    "stop_retained_variant": "Coding Exon",
    "start_lost": "Coding Exon",
    "start_retained_variant": "Coding Exon",
    "frameshift_variant": "Coding Exon",
    "inframe_insertion": "Coding Exon",
    "inframe_deletion": "Coding Exon",
    "coding_sequence_variant": "Coding Exon",
    "protein_altering_variant": "Coding Exon",
    "incomplete_terminal_codon_variant": "Coding Exon",

    # Splicing
    "splice_acceptor_variant": "Splicing Junction",
    "splice_donor_variant": "Splicing Junction",
    "splice_donor_5th_base_variant": "Splicing Junction",
    "splice_donor_region_variant": "Splicing Junction",
    "splice_polypyrimidine_tract_variant": "Splicing Junction",
    "splice_region_variant": "Splicing Junction",

    # Intronic
    "intron_variant": "Intron",
    "NMD_transcript_variant": "Intron",

    # UTR (kept distinct — see module docstring above)
    "5_prime_utr_variant": "Untranslated Region (5' UTR)",
    "3_prime_utr_variant": "Untranslated Region (3' UTR)",

    # Non-coding RNA
    "non_coding_transcript_exon_variant": "Non-Coding RNA",
    "non_coding_transcript_variant": "Non-Coding RNA",
    "mature_miRNA_variant": "Non-Coding RNA",

    # Regulatory
    "regulatory_region_variant": "Regulatory",
    "regulatory_region_ablation": "Regulatory",
    "regulatory_region_amplification": "Regulatory",
    "TF_binding_site_variant": "Regulatory",
    "TFBS_ablation": "Regulatory",
    "TFBS_amplification": "Regulatory",

    # Intergenic / flanking
    "upstream_gene_variant": "Non-Coding / Intergenic",
    "downstream_gene_variant": "Non-Coding / Intergenic",
    "intergenic_variant": "Non-Coding / Intergenic",
}

GENOMIC_REGION_DEFAULT = "Other / Unclassified"

# ---------------------------------------------------------------------------
# VEP REST query parameters required to receive the fields the frozen
# output schema depends on (3A §4.2 / §I-1 / §I-3).
# ---------------------------------------------------------------------------

REQUIRED_VEP_PARAMS: dict[str, int] = {
    "hgvs": 1,
    "mane_select": 1,
    "canonical": 1,
    "numbers": 1,
}

# ---------------------------------------------------------------------------
# Plugin / field suppression list (Conversation 3A, Part 10.1)
#
# The Ensembl VEP REST API returns these fields by default for many
# missense variants. They must never be re-exposed in VEPAnnotation or
# the public output envelope — they belong to other modules (or to no
# module yet) per the frozen scope decisions in 3A Part 2.3 / Part 10.
# This list exists purely as documentation / a self-check; the parser
# never reads these keys when building VEPAnnotation in the first place.
# ---------------------------------------------------------------------------

SUPPRESSED_RAW_FIELDS: tuple[str, ...] = (
    "polyphen_score",
    "polyphen_prediction",
    "sift_score",
    "sift_prediction",
    "cadd_phred",
    "cadd_raw",
    "revel",
    "lof",
    "lof_flags",
    "lof_filter",
    "spliceai_pred",
)

# Transcript selection provenance values (3A §5.2)
TRANSCRIPT_SOURCE_MANE_SELECT = "mane_select"
TRANSCRIPT_SOURCE_ENSEMBL_CANONICAL = "ensembl_canonical"
TRANSCRIPT_SOURCE_FALLBACK = "fallback"

# Output envelope status values
STATUS_OK = "ok"
STATUS_NO_DATA = "no_data"
STATUS_CACHE_HIT = "cache_hit"

ANNOTATION_SOURCE = "ensembl_vep_rest"
GENOME_BUILD = "GRCh38"

# Cache TTL: 30 days (3A §11.1) — Ensembl releases quarterly; this keeps
# cached annotations reasonably fresh without daily re-querying.
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60