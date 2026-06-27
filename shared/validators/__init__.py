"""
shared.validators
====================

Generic validation for the canonical variant representation that every
module's eventual `annotate(chrom, position, reference, alternate)`
interface will receive. These validators check FORM (is this a sane
chrom/pos/allele string), not biological truth (is this actually a real
variant in GRCh38) — biological correctness is checked at the
normalization stage, not here.

No tool-specific logic. VEP, gnomAD, STRING, etc. all call the same
`validate_variant(...)` before doing any work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.exceptions import ValidationError

_VALID_BASES = set("ACGTN")

# GRCh38 standard chromosome names: 1-22, X, Y, MT (Ensembl style, no "chr" prefix)
_VALID_CHROMS = {str(i) for i in range(1, 23)} | {"X", "Y", "MT"}


@dataclass(frozen=True)
class CanonicalVariant:
    """The single representation every module should accept.
    Construct only via `validate_variant()` — never build this directly
    from unvalidated input.
    """
    chrom: str
    position: int
    reference: str
    alternate: str
    genome_build: str = "GRCh38"

    @property
    def variant_id(self) -> str:
        return f"{self.chrom}:{self.position}:{self.reference}:{self.alternate}"


def normalize_chrom(raw: str) -> str:
    """Strip a leading 'chr' prefix if present (UCSC-style) so downstream
    comparisons against Ensembl-style names are consistent.
    """
    cleaned = raw.strip()
    if cleaned.lower().startswith("chr"):
        cleaned = cleaned[3:]
    if cleaned.upper() in {"M", "MT"}:
        cleaned = "MT"
    else:
        cleaned = cleaned.upper() if cleaned.upper() in {"X", "Y"} else cleaned
    return cleaned


def validate_chrom(raw: str) -> str:
    chrom = normalize_chrom(raw)
    if chrom not in _VALID_CHROMS:
        raise ValidationError(
            f"Invalid chromosome '{raw}' — expected one of {sorted(_VALID_CHROMS)}",
            context={"raw_value": raw},
        )
    return chrom


def validate_position(raw: int | str) -> int:
    try:
        position = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Position must be an integer, got {raw!r}", context={"raw_value": raw}
        ) from exc
    if position <= 0:
        raise ValidationError(
            f"Position must be a positive 1-based coordinate, got {position}",
            context={"raw_value": raw},
        )
    return position


def validate_allele(raw: str, *, field_name: str) -> str:
    """Validates a reference or alternate allele string. Accepts standard
    bases (A/C/G/T/N) and, for indels, longer sequences of those bases.
    Does NOT accept symbolic alleles (e.g. <DEL>, <INS>) — those require
    tool-specific handling and should be rejected at normalization, not
    silently passed through.
    """
    cleaned = raw.strip().upper()
    if not cleaned:
        raise ValidationError(f"{field_name} allele is empty", context={"raw_value": raw})
    if not set(cleaned).issubset(_VALID_BASES):
        raise ValidationError(
            f"{field_name} allele '{raw}' contains characters outside ACGTN "
            f"(symbolic alleles like <DEL> are not supported here)",
            context={"raw_value": raw, "field": field_name},
        )
    return cleaned


_HGVS_PATTERN = re.compile(r"^[\w.]+:[cgmnrp]\.")


def looks_like_hgvs(raw: str) -> bool:
    """Heuristic check used by the normalization layer to decide whether
    a string needs HGVS-to-genomic conversion before validate_variant()
    can be applied. Not itself a validator.
    """
    return bool(_HGVS_PATTERN.match(raw.strip()))


def validate_variant(
    chrom: str,
    position: int | str,
    reference: str,
    alternate: str,
    *,
    genome_build: str = "GRCh38",
) -> CanonicalVariant:
    """The single entrypoint every module should call before annotating.
    Raises ValidationError on any malformed input; never returns a
    partially-valid object.
    """
    if genome_build != "GRCh38":
        raise ValidationError(
            f"Only GRCh38 is supported by this framework, got '{genome_build}'. "
            "Convert/liftover at the normalization stage before reaching modules.",
            context={"genome_build": genome_build},
        )

    return CanonicalVariant(
        chrom=validate_chrom(chrom),
        position=validate_position(position),
        reference=validate_allele(reference, field_name="reference"),
        alternate=validate_allele(alternate, field_name="alternate"),
        genome_build=genome_build,
    )
