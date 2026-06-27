from __future__ import annotations

from typing import Optional

from shared.logging import get_logger

from modules.alphamissense.constants import (
    COL_ALT,
    COL_AM_CLASS,
    COL_AM_PATHOGENICITY,
    COL_CHROM,
    COL_POS,
    COL_PROTEIN_VARIANT,
    COL_REF,
    COL_TRANSCRIPT_ID,
    COL_UNIPROT_ID,
    EXPECTED_COLUMN_COUNT,
    FILE_CHROM_PREFIX,
    KNOWN_AM_CLASSES,
)
from modules.alphamissense.models import AlphaMissenseCandidate

log = get_logger(__name__)


def normalize_chrom_for_file(chrom: str) -> str:
    """Bare Ensembl-style ('1', 'X') -> file convention ('chr1', 'chrX')."""
    chrom = chrom.strip()
    if chrom.lower().startswith(FILE_CHROM_PREFIX):
        return chrom
    return f"{FILE_CHROM_PREFIX}{chrom}"


def normalize_chrom_from_file(chrom: str) -> str:
    """File convention ('chr1', 'chrX') -> bare Ensembl-style ('1', 'X')."""
    chrom = chrom.strip()
    if chrom.lower().startswith(FILE_CHROM_PREFIX):
        return chrom[len(FILE_CHROM_PREFIX):]
    return chrom


def _empty_to_none(value: str) -> Optional[str]:
    value = value.strip()
    if value == "" or value == ".":
        return None
    return value


def _parse_pathogenicity(value: str) -> Optional[float]:
    cleaned = _empty_to_none(value)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError:
        log.warning("Unparseable am_pathogenicity value", extra={"raw_value": value})
        return None


def _parse_am_class(value: str) -> Optional[str]:
    cleaned = _empty_to_none(value)
    if cleaned is None:
        return None
    if cleaned not in KNOWN_AM_CLASSES:
        log.warning("Unrecognized am_class value; passing through as-is", extra={"raw_value": cleaned})
    return cleaned


def parse_row(row: tuple) -> AlphaMissenseCandidate:
    if len(row) != EXPECTED_COLUMN_COUNT:
        raise ValueError(
            f"Unexpected AlphaMissense row shape: expected {EXPECTED_COLUMN_COUNT} "
            f"columns, got {len(row)}: {row!r}"
        )

    return AlphaMissenseCandidate(
        transcript_id=_empty_to_none(row[COL_TRANSCRIPT_ID]),
        uniprot_id=_empty_to_none(row[COL_UNIPROT_ID]),
        protein_variant=_empty_to_none(row[COL_PROTEIN_VARIANT]),
        am_pathogenicity=_parse_pathogenicity(row[COL_AM_PATHOGENICITY]),
        am_class=_parse_am_class(row[COL_AM_CLASS]),
    )


def parse_matching_rows(
    raw_rows: list,
    reference: str,
    alternate: str,
) -> list:
    """
    Parse raw tabix rows and keep only those whose REF/ALT match the
    queried allele exactly. A tabix fetch is position-based only, so a
    single position can legitimately return rows for *other* alternate
    alleles at the same site — those are not matches for this query and
    must be filtered out here, not treated as ambiguity.
    """
    reference = reference.strip().upper()
    alternate = alternate.strip().upper()

    candidates = []
    for row in raw_rows:
        row_ref = row[COL_REF].strip().upper()
        row_alt = row[COL_ALT].strip().upper()
        if row_ref != reference or row_alt != alternate:
            log.debug(
                "Skipping row at queried position with non-matching allele",
                extra={"row_ref": row_ref, "row_alt": row_alt, "queried_ref": reference, "queried_alt": alternate},
            )
            continue
        candidates.append(parse_row(row))

    return candidates