"""
modules.vep.parser
=====================

Pure functions that turn a raw Ensembl VEP REST JSON record into a
``VEPAnnotation``. Nothing here touches the network, the cache, or
``shared.config`` — it only transforms data that has already been
fetched, which makes every function in this file trivially unit
testable against fixture JSON.

This is where the frozen transcript selection policy (3A Part 5) lives.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logging import get_logger
from shared.validators import CanonicalVariant

from modules.vep.constants import (
    GENOMIC_REGION_DEFAULT,
    GENOMIC_REGION_MAP,
    TRANSCRIPT_SOURCE_ENSEMBL_CANONICAL,
    TRANSCRIPT_SOURCE_FALLBACK,
    TRANSCRIPT_SOURCE_MANE_SELECT,
)
from modules.vep.models import VEPAnnotation

log = get_logger(__name__)


def map_genomic_region(most_severe_consequence: Optional[str]) -> str:
    """Translate a VEP SO term into the framework's coarser structural
    classification (3A §6.2). Unknown/unmapped terms fall back to
    ``"Other / Unclassified"`` rather than raising — an incomplete
    mapping table is a documentation gap, not a fatal error.
    """
    if most_severe_consequence is None:
        return GENOMIC_REGION_DEFAULT
    return GENOMIC_REGION_MAP.get(most_severe_consequence, GENOMIC_REGION_DEFAULT)


def select_transcript(
    transcript_consequences: list[dict[str, Any]],
    *,
    variant_id: str,
) -> tuple[Optional[dict[str, Any]], str]:
    """Frozen transcript selection policy (3A Part 5.2):

        1. MANE Select transcript (``mane_select`` key present)
        2. Ensembl Canonical transcript (``canonical == 1``)
        3. ``transcript_consequences[0]`` — last resort, logged as
           WARNING; this should essentially never fire for
           protein-coding genes.

    Returns ``(selected_transcript_or_None, transcript_source)``.
    ``selected_transcript`` is ``None`` only when
    ``transcript_consequences`` is empty (e.g. a true intergenic
    variant) — in that case ``transcript_source`` is also ``None``-like
    in the caller's sense, but for simplicity this function reports
    ``"fallback"`` is not used; callers should check for ``None`` first.
    """
    if not transcript_consequences:
        return None, ""

    for tx in transcript_consequences:
        if "mane_select" in tx:
            return tx, TRANSCRIPT_SOURCE_MANE_SELECT

    for tx in transcript_consequences:
        if tx.get("canonical") == 1:
            log.info(
                "No MANE Select transcript; using Ensembl Canonical",
                extra={"variant": variant_id},
            )
            return tx, TRANSCRIPT_SOURCE_ENSEMBL_CANONICAL

    log.warning(
        "No MANE Select or Canonical transcript; falling back to "
        "transcript_consequences[0]",
        extra={"variant": variant_id},
    )
    return transcript_consequences[0], TRANSCRIPT_SOURCE_FALLBACK


def _none_if_missing(value: Any) -> Any:
    """Normalize VEP's occasional empty-string / 'None'-string fields to
    Python ``None``. The Ensembl API does not consistently omit absent
    fields vs. returning an empty string, so this normalization happens
    at the parser boundary rather than trusting ``.get()`` alone.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() in ("", "None", "Unknown", "N/A"):
        return None
    return value


def _stringify(value: Any) -> Optional[str]:
    """Coerce a non-missing value to ``str`` to match the frozen
    ``Optional[str]`` schema for positional fields — Ensembl returns
    ``cdna_start``/``cds_start``/``protein_start`` as JSON integers, but
    the output schema (3A §6.1) types them as strings for consistency
    with ``exon_number``/``intron_number`` (e.g. ``"6/11"``-style values
    aren't representable as plain ints anyway).
    """
    value = _none_if_missing(value)
    return None if value is None else str(value)


def parse_vep_record(
    raw_record: dict[str, Any],
    *,
    variant: CanonicalVariant,
    ensembl_release: Optional[str],
) -> VEPAnnotation:
    """Build a ``VEPAnnotation`` from one raw Ensembl VEP REST record.

    Never indexes by position for biology-bearing fields — every access
    is by name via ``.get()``, per the future-compatibility rule in 3A
    §4.7. Fields not in the frozen output schema (PolyPhen, SIFT, CADD,
    LOFTEE, ...) are read by nothing in this function and therefore
    never re-exposed, satisfying the plugin suppression policy (3A Part
    10.1) implicitly rather than via an explicit filter step.
    """
    most_severe = _none_if_missing(raw_record.get("most_severe_consequence"))
    transcript_consequences = raw_record.get("transcript_consequences") or []

    selected_tx, transcript_source = select_transcript(
        transcript_consequences, variant_id=variant.variant_id
    )
    selected_tx = selected_tx or {}

    amino_acids = _none_if_missing(selected_tx.get("amino_acids"))
    codons = _none_if_missing(selected_tx.get("codons"))
    exon = _none_if_missing(selected_tx.get("exon"))
    intron = _none_if_missing(selected_tx.get("intron"))

    return VEPAnnotation(
        variant_id=variant.variant_id,
        chrom=variant.chrom,
        position=variant.position,
        reference=variant.reference,
        alternate=variant.alternate,
        genome_build=variant.genome_build,
        gene_symbol=_none_if_missing(selected_tx.get("gene_symbol")),
        gene_id=_none_if_missing(selected_tx.get("gene_id")),
        biotype=_none_if_missing(selected_tx.get("biotype")),
        strand=selected_tx.get("strand"),
        most_severe_consequence=most_severe,
        impact=_none_if_missing(selected_tx.get("impact")),
        genomic_region=map_genomic_region(most_severe),
        transcript_id=_none_if_missing(selected_tx.get("transcript_id")),
        transcript_source=transcript_source or None,
        transcript_count=len(transcript_consequences),
        hgvs_c=_none_if_missing(selected_tx.get("hgvsc")),
        hgvs_p=_none_if_missing(selected_tx.get("hgvsp")),
        amino_acid_change=amino_acids,
        codon_change=codons,
        exon_number=exon,
        intron_number=intron,
        cdna_position=_none_if_missing(selected_tx.get("cdna_start")),
        cds_position=_none_if_missing(selected_tx.get("cds_start")),
        protein_position=_none_if_missing(selected_tx.get("protein_start")),
        ensembl_release=ensembl_release,
        status="ok",
    )