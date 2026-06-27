"""
modules/gnomad/parser.py

All gnomAD-specific parsing logic lives here, and ONLY here. Per the
AlphaMissense precedent ("all biological parsing remains module-specific")
and the shared/indexed_files boundary rule, neither `shared.http` nor any
future `shared.indexed_files`-based local backend should ever need to
duplicate this logic — both backends produce the same
"raw variant dict" -> GnomadAnnotation transformation through this module.

IMPORTANT DEVIATION FROM THE FROZEN DESIGN DOC (flagged explicitly, not
silently implemented):

gnomAD_Module_Design.md Section 14 specifies a single `af_overall` /
`ac_overall` / `an_overall` field set, implicitly assuming gnomAD exposes
one pre-combined "joint" frequency. The actual GraphQL schema (confirmed
against the Conversation 5B proof-of-concept script) returns SEPARATE
`exome` and `genome` blocks, each with independent `af` / `ac` / `an` /
`homozygote_count` / `filters` / `populations`. There is no single
pre-combined field gnomAD hands back directly.

This module therefore computes the "overall" fields by combining exome +
genome at the allele-count level — the scientifically correct way to
combine two frequency estimates is to sum allele counts and sample sizes
and recompute the ratio, NOT to average the two `af` values (averaging
two frequencies with very different sample sizes is statistically wrong
and would silently bias `af_overall` toward whichever subset is smaller).

    ac_overall = ac_exome + ac_genome
    an_overall = an_exome + an_genome
    af_overall = ac_overall / an_overall   (None if an_overall == 0)

This is a parsing-layer decision, not a redesign of the frozen schema —
the *output field names* (`af_overall`, `ac_overall`, `an_overall`,
`af_popmax`, `popmax_population`, `population_frequencies`,
`n_homozygotes`, `filter_status`) are unchanged from the design doc.
Only how they are computed differs from what was originally assumed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    ANNOTATION_SOURCE_REMOTE,
    STATUS_LOW_CONFIDENCE,
    STATUS_OK,
)

# gnomAD's own "passed all site-level QC filters" sentinel. A non-empty
# filters list (e.g. ["AC0"], ["InbreedingCoeff"]) means the site is
# flagged; an empty list means PASS. We never invent this rule — it is
# gnomAD's own filtering convention, simply surfaced rather than
# reinterpreted (frozen design Section 15 / 23).
_PASS_FILTER_VALUE = "PASS"


def _combine_subset(
    exome: Optional[Dict[str, Any]], genome: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Combine the exome and genome subsets of a gnomAD variant record into
    one set of "overall" allele-count-weighted statistics.

    Either `exome` or `genome` may be None if that sequencing subset does
    not cover this site at all (a real, expected gnomAD condition — NOT
    an error). Missing AND zero are different things: a missing subset
    contributes 0 to both ac and an (i.e. it simply does not add
    information), which is the correct way to fold an absent subset into
    a combined ac/an sum.
    """
    ac_exome = (exome or {}).get("ac") or 0
    an_exome = (exome or {}).get("an") or 0
    ac_genome = (genome or {}).get("ac") or 0
    an_genome = (genome or {}).get("an") or 0

    ac_overall = ac_exome + ac_genome
    an_overall = an_exome + an_genome
    af_overall = (ac_overall / an_overall) if an_overall > 0 else None

    hom_exome = (exome or {}).get("homozygote_count") or 0
    hom_genome = (genome or {}).get("homozygote_count") or 0
    n_homozygotes = hom_exome + hom_genome

    return {
        "ac_overall": ac_overall if an_overall > 0 else None,
        "an_overall": an_overall if an_overall > 0 else None,
        "af_overall": af_overall,
        "n_homozygotes": n_homozygotes if (exome or genome) else None,
    }


def _combine_filters(
    exome: Optional[Dict[str, Any]], genome: Optional[Dict[str, Any]]
) -> Optional[str]:
    """
    Combine site-level QC filters from whichever subset(s) are present.

    Frozen rule (Section 15): a flagged filter is surfaced, never hidden.
    If either subset carries a non-PASS flag, the combined `filter_status`
    reflects that. Filters are deduplicated but not reinterpreted.
    """
    flags: List[str] = []
    for subset in (exome, genome):
        if not subset:
            continue
        subset_filters = subset.get("filters") or []
        for flag in subset_filters:
            if flag and flag not in flags:
                flags.append(flag)

    if not flags:
        # No subset present at all -> unknown, not PASS.
        if exome is None and genome is None:
            return None
        return _PASS_FILTER_VALUE

    return ",".join(sorted(flags))


def _combine_populations(
    exome: Optional[Dict[str, Any]], genome: Optional[Dict[str, Any]]
) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Build the per-population breakdown (Section 14: `population_frequencies`)
    by combining exome+genome ac/an per population code, using the same
    allele-count-weighted approach as `_combine_subset`.
    """
    by_pop: Dict[str, Dict[str, int]] = {}

    for subset in (exome, genome):
        if not subset:
            continue
        for pop in subset.get("populations") or []:
            pop_id = pop.get("id")
            if not pop_id:
                continue
            entry = by_pop.setdefault(pop_id, {"ac": 0, "an": 0})
            entry["ac"] += pop.get("ac") or 0
            entry["an"] += pop.get("an") or 0

    result: Dict[str, Dict[str, Optional[float]]] = {}
    for pop_id, counts in by_pop.items():
        an = counts["an"]
        ac = counts["ac"]
        result[pop_id] = {
            "af": (ac / an) if an > 0 else None,
            "ac": ac if an > 0 else None,
            "an": an if an > 0 else None,
        }
    return result


def _compute_popmax(
    population_frequencies: Dict[str, Dict[str, Optional[float]]]
) -> "tuple[Optional[float], Optional[str]]":
    """
    Derive `af_popmax` / `popmax_population` (Section 14) from the
    combined per-population breakdown.

    gnomAD's own GraphQL schema exposes a `popmax`/`popmax_population`
    field on older dataset versions, but it is not part of the `variant`
    query shape used here (and is deprecated/inconsistent across gnomAD
    releases). Deriving it locally from `population_frequencies` is more
    robust across dataset versions and keeps this module's output stable
    even if gnomAD changes how (or whether) it exposes popmax directly.
    """
    best_af: Optional[float] = None
    best_pop: Optional[str] = None
    for pop_id, stats in population_frequencies.items():
        af = stats.get("af")
        if af is None:
            continue
        if best_af is None or af > best_af:
            best_af = af
            best_pop = pop_id
    return best_af, best_pop


def parse_variant_response(
    raw_variant: Optional[Dict[str, Any]],
    variant_id: str,
    dataset: str,
) -> Dict[str, Any]:
    """
    Transform a raw `data.variant` GraphQL object (or None, if not found)
    into the field dict matching the frozen `GnomadAnnotation` schema.

    This function never raises for "not found" — that is a valid,
    expected `status=no_data` outcome (Section 21 / 22), not an error.
    """
    if raw_variant is None:
        return {
            "variant_id": variant_id,
            "af_overall": None,
            "ac_overall": None,
            "an_overall": None,
            "af_popmax": None,
            "popmax_population": None,
            "population_frequencies": {},
            "filter_status": None,
            "n_homozygotes": None,
            "source_dataset": dataset,
            "data_release": dataset,
            "annotation_source": ANNOTATION_SOURCE_REMOTE,
            "status": "no_data",
        }

    exome = raw_variant.get("exome")
    genome = raw_variant.get("genome")

    overall = _combine_subset(exome, genome)
    filter_status = _combine_filters(exome, genome)
    population_frequencies = _combine_populations(exome, genome)
    af_popmax, popmax_population = _compute_popmax(population_frequencies)

    # Frozen status logic (Section 22 / 23): a site with any non-PASS flag
    # is still returned in full (never dropped), but flagged as
    # low_confidence rather than a plain "ok".
    status = STATUS_OK
    if filter_status and filter_status != _PASS_FILTER_VALUE:
        status = STATUS_LOW_CONFIDENCE

    return {
        "variant_id": variant_id,
        "af_overall": overall["af_overall"],
        "ac_overall": overall["ac_overall"],
        "an_overall": overall["an_overall"],
        "af_popmax": af_popmax,
        "popmax_population": popmax_population,
        "population_frequencies": population_frequencies,
        "filter_status": filter_status,
        "n_homozygotes": overall["n_homozygotes"],
        "source_dataset": dataset,
        "data_release": dataset,
        "annotation_source": ANNOTATION_SOURCE_REMOTE,
        "status": status,
    }