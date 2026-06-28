from __future__ import annotations

from typing import Optional

from shared.logging import get_logger

from modules.spliceai.constants import (
    ENTRY_FIELD_COUNT,
    ENTRY_IDX_ALLELE,
    ENTRY_IDX_DP_AG,
    ENTRY_IDX_DP_AL,
    ENTRY_IDX_DP_DG,
    ENTRY_IDX_DP_DL,
    ENTRY_IDX_DS_AG,
    ENTRY_IDX_DS_AL,
    ENTRY_IDX_DS_DG,
    ENTRY_IDX_DS_DL,
    ENTRY_IDX_SYMBOL,
    FILE_CHROM_PREFIX,
    SPLICEAI_INFO_KEY,
    VCF_COL_INFO,
    VCF_EXPECTED_MIN_COLUMNS,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Chromosome normalisation
# ---------------------------------------------------------------------------

def normalize_chrom_for_file(chrom: str) -> str:
    """Bare Ensembl-style ('1', 'X') -> file convention ('chr1', 'chrX')."""
    chrom = chrom.strip()
    if chrom.lower().startswith(FILE_CHROM_PREFIX):
        return chrom
    return f"{FILE_CHROM_PREFIX}{chrom}"


# ---------------------------------------------------------------------------
# Scalar field parsers
# ---------------------------------------------------------------------------

def _dot_to_none(value: str) -> Optional[str]:
    """Return None for '.' or empty string; otherwise return stripped value."""
    stripped = value.strip()
    if stripped == "" or stripped == ".":
        return None
    return stripped


def _parse_delta_score(raw: str) -> Optional[float]:
    """Parse a DS_* field. Returns None for '.' or unparseable values."""
    cleaned = _dot_to_none(raw)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError:
        log.warning(
            "Unparseable SpliceAI delta score; treating as None",
            extra={"raw_value": raw},
        )
        return None


def _parse_delta_position(raw: str) -> Optional[int]:
    """Parse a DP_* field. Returns None for '.' or unparseable values."""
    cleaned = _dot_to_none(raw)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except ValueError:
        log.warning(
            "Unparseable SpliceAI delta position; treating as None",
            extra={"raw_value": raw},
        )
        return None


# ---------------------------------------------------------------------------
# INFO-field extraction
# ---------------------------------------------------------------------------

def _extract_spliceai_info_value(info: str) -> Optional[str]:
    """
    Extract the value part of 'SpliceAI=...' from a VCF INFO string.

    The INFO string is semicolon-delimited key=value pairs. We search for
    the key 'SpliceAI' specifically so we don't accidentally match a key
    that happens to contain the substring. Returns None if not found.
    """
    for token in info.split(";"):
        token = token.strip()
        if token.startswith(SPLICEAI_INFO_KEY + "="):
            return token[len(SPLICEAI_INFO_KEY) + 1:]
    return None


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------

def _parse_entry(entry: str) -> Optional[dict]:
    """
    Parse one pipe-delimited SpliceAI entry:
        ALLELE|SYMBOL|DS_AG|DS_AL|DS_DG|DS_DL|DP_AG|DP_AL|DP_DG|DP_DL

    Returns a dict of parsed fields, or None if the entry is malformed.
    Per design Section 11 rule 6: '.' fields become None but the entry
    is still valid (status='ok', not 'no_data').
    """
    parts = entry.split("|")
    if len(parts) != ENTRY_FIELD_COUNT:
        log.warning(
            "SpliceAI entry has unexpected field count; skipping",
            extra={"entry": entry, "expected": ENTRY_FIELD_COUNT, "got": len(parts)},
        )
        return None

    return {
        "allele":    parts[ENTRY_IDX_ALLELE].strip().upper(),
        "symbol":    _dot_to_none(parts[ENTRY_IDX_SYMBOL]),
        "ds_ag":     _parse_delta_score(parts[ENTRY_IDX_DS_AG]),
        "ds_al":     _parse_delta_score(parts[ENTRY_IDX_DS_AL]),
        "ds_dg":     _parse_delta_score(parts[ENTRY_IDX_DS_DG]),
        "ds_dl":     _parse_delta_score(parts[ENTRY_IDX_DS_DL]),
        "dp_ag":     _parse_delta_position(parts[ENTRY_IDX_DP_AG]),
        "dp_al":     _parse_delta_position(parts[ENTRY_IDX_DP_AL]),
        "dp_dg":     _parse_delta_position(parts[ENTRY_IDX_DP_DG]),
        "dp_dl":     _parse_delta_position(parts[ENTRY_IDX_DP_DL]),
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def parse_variant_rows(
    rows: list[tuple[str, ...]],
    alternate: str,
) -> Optional[dict]:
    """
    Given raw tabix row-tuples from the SpliceAI masked SNV VCF and the
    queried alternate allele, return the parsed field dict for the matching
    SpliceAI entry, or None if no match is found.

    Implements the full matching logic from design Section 11:

    - Zero rows -> None (no_data).
    - One or more rows, none with a matching ALLELE -> None (no_data).
    - Matching ALLELE found -> return parsed fields (status='ok').
      If Illumina recorded '.' for any field, that field is None, but the
      result is still returned as status='ok' (not discarded as no_data).

    The ALLELE match key is used (not positional ALT-column correspondence)
    because Illumina's format explicitly tags each entry with its allele
    precisely so consumers don't have to rely on positional alignment.

    `alternate` must already be uppercase (validate_variant() ensures this).
    """
    alternate_upper = alternate.strip().upper()

    for row in rows:
        if len(row) < VCF_EXPECTED_MIN_COLUMNS:
            log.warning(
                "SpliceAI VCF row has too few columns; skipping",
                extra={"row": row, "expected_min": VCF_EXPECTED_MIN_COLUMNS},
            )
            continue

        info = row[VCF_COL_INFO]
        spliceai_value = _extract_spliceai_info_value(info)

        if spliceai_value is None:
            log.warning(
                "SpliceAI VCF row has no SpliceAI= INFO field; skipping",
                extra={"info": info},
            )
            continue

        # The value is comma-separated: one entry per ALT allele at this row.
        for raw_entry in spliceai_value.split(","):
            raw_entry = raw_entry.strip()
            if not raw_entry:
                continue
            parsed = _parse_entry(raw_entry)
            if parsed is None:
                continue
            if parsed["allele"] == alternate_upper:
                log.debug(
                    "Matched SpliceAI entry for alternate allele",
                    extra={"alternate": alternate_upper, "symbol": parsed["symbol"]},
                )
                return parsed

    return None