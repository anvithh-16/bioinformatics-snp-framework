"""
modules.vep.models
====================

The frozen VEPAnnotation dataclass (Conversation 3A, Part 6.1) and the
output envelope builder. No business logic lives here — only the shape
of the data and trivial (de)serialization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from modules.vep.constants import ANNOTATION_SOURCE, GENOME_BUILD


@dataclass(frozen=True)
class VEPAnnotation:
    """The VEP module's internal output schema, frozen in Conversation 3A.

    All ``Optional`` fields default to ``None`` when the underlying data
    is absent from the Ensembl response — never the string ``"None"``,
    ``"Unknown"``, or ``""`` (PROJECT_CONTEXT.md: "Missing annotations
    are represented explicitly. Use None.").

    ``transcript_count`` is the one exception: it defaults to ``0``
    (int), because zero overlapping transcripts is itself a correct,
    meaningful value rather than a missing one.
    """

    # --- Variant identity (from input, validated) ---
    variant_id: str          # "CHROM:POSITION:REF:ALT" (colon-separated)
    chrom: str
    position: int
    reference: str
    alternate: str
    genome_build: str = GENOME_BUILD

    # --- Gene context ---
    gene_symbol: Optional[str] = None
    gene_id: Optional[str] = None
    biotype: Optional[str] = None
    strand: Optional[int] = None

    # --- Primary consequence ---
    most_severe_consequence: Optional[str] = None
    impact: Optional[str] = None
    genomic_region: Optional[str] = None

    # --- Selected transcript ---
    transcript_id: Optional[str] = None
    transcript_source: Optional[str] = None
    transcript_count: int = 0

    # --- HGVS notation ---
    hgvs_c: Optional[str] = None
    hgvs_p: Optional[str] = None

    # --- Amino acid / codon level ---
    amino_acid_change: Optional[str] = None
    codon_change: Optional[str] = None

    # --- Positional ---
    exon_number: Optional[str] = None
    intron_number: Optional[str] = None

    # --- Optional positional context (3A Part 1.4, O-1/O-2) ---
    cdna_position: Optional[str] = None
    cds_position: Optional[str] = None
    protein_position: Optional[str] = None

    # --- Provenance ---
    ensembl_release: Optional[str] = None
    annotation_source: str = ANNOTATION_SOURCE

    # --- Status ---
    status: str = "ok"   # "ok" | "no_data" | "cache_hit"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_output_envelope(
    *,
    variant_id: str,
    status: str,
    annotation: VEPAnnotation,
    ensembl_release: Optional[str],
) -> dict[str, Any]:
    """Wrap a VEPAnnotation in the standard framework envelope, per the
    pattern documented in ``shared/README.md`` and frozen in 3A §6.4::

        {
            "variant_id": ...,
            "module_name": "vep",
            "status": ...,
            "fields": annotation.to_dict(),
            "source_version": ensembl_release,
        }
    """
    return {
        "variant_id": variant_id,
        "module_name": "vep",
        "status": status,
        "fields": annotation.to_dict(),
        "source_version": ensembl_release,
    }