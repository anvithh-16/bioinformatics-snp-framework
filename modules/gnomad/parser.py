"""
modules/gnomad/parser.py

All gnomAD-specific parsing logic lives here, and ONLY here. Per the
AlphaMissense precedent ("all biological parsing remains module-specific")
and the shared/indexed_files boundary rule, neither `shared.http` nor any
future `shared.indexed_files`-based local backend should ever need to
duplicate this logic.

=== CORRECTION FROM POST-IMPLEMENTATION REVIEW ===

The first version of this file derived "overall" statistics (af_overall,
ac_overall, an_overall, n_homozygotes, population_frequencies) by
manually summing gnomAD's separate `exome` and `genome` blocks
client-side: `ac_overall = ac_exome + ac_genome`, etc.

This was a real correctness bug, not a style choice. gnomAD's GraphQL
API exposes a THIRD block, `joint`, which is the Broad Institute's own
server-computed combination of exome+genome -- the authoritative source
for "overall" statistics. This was confirmed against two independently
written, currently-working scripts that query the live gnomAD v4 API
(one of them explicitly documents printing "Joint Data: Allele Count
(AC) / Allele Number (AN) / Homozygote Count" as a distinct block from
Exome Data and Genome Data).

Manually re-deriving "overall" stats by naive AC/AN summation is exactly
the kind of "don't trust the official computed value, recompute it
yourself" mistake this project has explicitly tried to avoid elsewhere
(see the MutPred2 lookup-table-only anti-pattern referenced in
Project_Context history). Naive summation also risks silently diverging
from gnomAD's actual combination logic -- v4.1's combined-filtering model
(EXOMES_FILTERED / GENOMES_FILTERED / BOTH_FILTERED) shows that "joint"
is not guaranteed to be pure arithmetic addition of the two subsets in
all cases (e.g. a variant filtered out in one subset's QC may be
excluded from that subset's contribution to the joint computation in a
way this module has no way of replicating correctly from the outside).

This file now reads af_overall / ac_overall / an_overall / n_homozygotes
/ population_frequencies DIRECTLY from the `joint` block. `exome` and
`genome` are still parsed, but only to derive `filter_status` (Section
15/23) -- they are no longer used to compute any frequency statistic.

The output field names are UNCHANGED from the frozen design schema
(gnomAD_Module_Design.md Section 14). Only how they are computed
changed -- first from an incorrect assumption (one pre-combined field),
then corrected again here (combined via `joint`, not manual summation).
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
# flagged; an empty list means PASS. We never invent this rule -- it is
# gnomAD's own filtering convention, simply surfaced rather than
# reinterpreted (frozen design Section 15 / 23).
_PASS_FILTER_VALUE = "PASS"


def _safe_ratio(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    """
    ac/an -> af, defensively. Returns None (never 0.0, never a ZeroDivisionError)
    when either value is missing or an is zero -- a missing/zero allele
    number means "we don't have a usable frequency," not "the frequency
    is zero" (Section 21).
    """
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _extract_joint_stats(joint: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Derive the "overall" statistics directly from gnomAD's own
    server-computed `joint` block -- the authoritative combination of
    exome + genome. This function does NOT re-derive anything from
    exome/genome; it only reads what gnomAD already computed.
    """
    if not joint:
        return {
            "ac_overall": None,
            "an_overall": None,
            "af_overall": None,
            "n_homozygotes": None,
            "population_frequencies": {},
        }

    ac = joint.get("ac")
    an = joint.get("an")
    homozygote_count = joint.get("homozygote_count")

    population_frequencies: Dict[str, Dict[str, Optional[float]]] = {}
    for pop in joint.get("populations") or []:
        pop_id = pop.get("id")
        if not pop_id:
            continue
        pop_ac = pop.get("ac")
        pop_an = pop.get("an")
        population_frequencies[pop_id] = {
            "af": _safe_ratio(pop_ac, pop_an),
            "ac": pop_ac,
            "an": pop_an,
        }

    return {
        "ac_overall": ac,
        "an_overall": an,
        "af_overall": _safe_ratio(ac, an),
        "n_homozygotes": homozygote_count,
        "population_frequencies": population_frequencies,
    }


def _combine_filters(
    exome: Optional[Dict[str, Any]], genome: Optional[Dict[str, Any]]
) -> Optional[str]:
    """
    Combine site-level QC filters from whichever subset(s) are present.

    Frozen rule (Section 15): a flagged filter is surfaced, never hidden.
    If either subset carries a non-PASS flag, the combined `filter_status`
    reflects that. Filters are deduplicated but not reinterpreted.

    NOTE: `joint` does not appear to expose its own `filters` field in
    either reference script consulted during review, so filter_status
    is necessarily derived from exome/genome, not joint. This is a
    flagged assumption about the `filters` field placement -- see
    constants.py and the module README's "Known limitations" section.
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


def _compute_popmax(
    population_frequencies: Dict[str, Dict[str, Optional[float]]]
) -> "tuple[Optional[float], Optional[str]]":
    """
    Derive `af_popmax` / `popmax_population` (Section 14) from the
    `joint`-derived per-population breakdown.

    gnomAD's GraphQL schema does not consistently expose a direct
    `popmax`/`popmax_population` field across dataset versions, so this
    is computed locally from `population_frequencies`, exactly as
    before this review -- this part of the original design was correct
    and is unchanged.
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

    This function never raises for "not found" -- that is a valid,
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
    joint = raw_variant.get("joint")

    joint_stats = _extract_joint_stats(joint)
    filter_status = _combine_filters(exome, genome)
    af_popmax, popmax_population = _compute_popmax(
        joint_stats["population_frequencies"]
    )

    # Frozen status logic (Section 22 / 23): a site with any non-PASS flag
    # is still returned in full (never dropped), but flagged as
    # low_confidence rather than a plain "ok".
    status = STATUS_OK
    if filter_status and filter_status != _PASS_FILTER_VALUE:
        status = STATUS_LOW_CONFIDENCE
    elif joint_stats["an_overall"] is None:
        # joint block missing/empty even though the variant itself was
        # found -- a real but unusual condition worth flagging rather
        # than silently reporting status="ok" with all-None frequencies.
        status = STATUS_LOW_CONFIDENCE

    return {
        "variant_id": variant_id,
        "af_overall": joint_stats["af_overall"],
        "ac_overall": joint_stats["ac_overall"],
        "an_overall": joint_stats["an_overall"],
        "af_popmax": af_popmax,
        "popmax_population": popmax_population,
        "population_frequencies": joint_stats["population_frequencies"],
        "filter_status": filter_status,
        "n_homozygotes": joint_stats["n_homozygotes"],
        "source_dataset": dataset,
        "data_release": dataset,
        "annotation_source": ANNOTATION_SOURCE_REMOTE,
        "status": status,
    }