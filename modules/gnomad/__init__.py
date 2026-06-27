"""
modules/gnomad/__init__.py

Public interface for the gnomAD module: the `annotate()` function and the
`GnomadAnnotation` dataclass. This is the only entry point other modules
or the pipeline integration layer should ever import from.

    from modules.gnomad import annotate
    result = annotate("1", 55051215, "G", "A")

Follows the exact validate -> cache -> backend -> envelope pattern
documented in Shared_README.md's quickstart and already used by VEP.

Backend selection (Section 8/9 of the frozen design): this conversation
implements ONLY the remote GraphQL backend (`GnomadRemoteClient`). The
local Tabix/VCF backend (`GnomadLocalClient`) is out of scope here, but
this function is structured so that adding it later means adding a branch
on `cfg.gnomad_backend` (or equivalent) inside `_get_backend()` only —
`annotate()`'s signature, validation, caching, and envelope logic do not
change.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from shared.cache import DiskCache, make_key
from shared.config import get_config
from shared.logging import get_logger
from shared.validators import validate_variant

from .client import GnomadRemoteClient
from .constants import MODULE_NAME
from .parser import parse_variant_response

log = get_logger(__name__)

# Module-level cache handle, lazily created on first use (mirrors the
# pattern implied by Shared_README.md's quickstart, where the DiskCache is
# constructed from `cfg.cache_dir`). Kept private; callers never touch it
# directly.
_cache: Optional[DiskCache] = None

# Cache TTL per frozen design Section 18: gnomAD releases are infrequent
# and not on a fixed schedule, so a longer default TTL than VEP's 30 days
# is appropriate. 90 days = 7_776_000 seconds.
_CACHE_TTL_SECONDS = 7_776_000

# Lazily constructed remote client (stateless aside from holding an
# HttpClient handle, safe to share across calls within a process).
_remote_client: Optional[GnomadRemoteClient] = None


@dataclass
class GnomadAnnotation:
    """
    Frozen output schema (gnomAD_Module_Design.md Section 13).

    All fields default to None except the bookkeeping fields that are
    always populated (variant_id, source_dataset, data_release,
    annotation_source, status) — missing biological values are Python
    `None`, never the strings "None"/""/"Unknown" (Section 21).
    """

    variant_id: str
    af_overall: Optional[float]
    ac_overall: Optional[int]
    an_overall: Optional[int]
    af_popmax: Optional[float]
    popmax_population: Optional[str]
    population_frequencies: Dict[str, Dict[str, Optional[float]]]
    filter_status: Optional[str]
    n_homozygotes: Optional[int]
    source_dataset: str
    data_release: str
    annotation_source: str
    status: str


def _get_cache() -> DiskCache:
    global _cache
    if _cache is None:
        cfg = get_config()
        _cache = DiskCache(
            cfg.cache_dir / "gnomad.sqlite",
            default_ttl_seconds=_CACHE_TTL_SECONDS,
        )
    return _cache


def _get_backend() -> GnomadRemoteClient:
    """
    Returns the active gnomAD backend.

    Only the remote backend exists in this conversation. A future
    GnomadLocalClient would be selected here based on configuration
    (e.g. `cfg.gnomad_backend == "local"`), without `annotate()` itself
    needing to change.
    """
    global _remote_client
    if _remote_client is None:
        _remote_client = GnomadRemoteClient()
    return _remote_client


def _to_gnomad_variant_id(chrom: str, position: int, reference: str, alternate: str) -> str:
    """
    gnomAD's own GraphQL API expects its native `chrom-pos-ref-alt`
    notation (confirmed against the Conversation 5B proof-of-concept
    script), which is a different separator convention from this
    framework's internal `CanonicalVariant.variant_id` (colon-separated,
    per VEP's I-7 fix). This conversion is intentionally local to the
    gnomAD module — it is gnomAD-API-specific, not a framework-wide
    convention, so it does not belong in `shared.validators`.
    """
    chrom_normalized = chrom[3:] if chrom.lower().startswith("chr") else chrom
    return f"{chrom_normalized}-{position}-{reference}-{alternate}"


def annotate(
    chrom: str, position: int, reference: str, alternate: str
) -> Dict[str, Any]:
    """
    Annotate a single SNV with gnomAD population allele frequency data.

    Returns the standard framework envelope:
        {
            "variant_id": ...,
            "module_name": "gnomad",
            "status": ...,
            "fields": {... GnomadAnnotation fields ...},
            "source_version": ...,
        }

    Raises:
        ValidationError: invalid chrom/position/reference/alternate.
        AnnotationUnavailableError: gnomAD's GraphQL API explicitly
            rejected the query (see GnomadRemoteClient.fetch_variant_data).
            A variant simply absent from gnomAD is NOT an error — it is
            returned as `status="no_data"` with all frequency fields None.
        NetworkError / RateLimitError: transport-level failures, raised
            internally by shared.http.HttpClient and allowed to propagate.
    """
    variant = validate_variant(chrom, position, reference, alternate)

    cfg = get_config()
    dataset = cfg.versions.gnomad_version
    if not dataset:
        # Mirrors VEP's reproducibility requirement: an unpinned version
        # must never silently proceed (Section 20 / Project_Context.md
        # "Pin versions whenever possible").
        from shared.exceptions import ValidationError

        raise ValidationError(
            "gnomad_version is not pinned in config.yaml under `versions`. "
            "Refusing to annotate with an unpinned gnomAD dataset version.",
        )

    cache = _get_cache()
    cache_key = make_key(
        "gnomad",
        "remote",
        dataset,
        variant.chrom,
        variant.position,
        variant.reference,
        variant.alternate,
    )

    cached = cache.get(cache_key)
    if cached is not None:
        log.debug("gnomAD cache hit", extra={"variant_id": variant.variant_id})
        return cached

    gnomad_variant_id = _to_gnomad_variant_id(
        variant.chrom, variant.position, variant.reference, variant.alternate
    )

    backend = _get_backend()
    raw_variant = backend.fetch_variant_data(gnomad_variant_id, dataset)

    fields = parse_variant_response(raw_variant, gnomad_variant_id, dataset)
    annotation = GnomadAnnotation(**fields)

    result = {
        "variant_id": variant.variant_id,
        "module_name": MODULE_NAME,
        "status": annotation.status,
        "fields": asdict(annotation),
        "source_version": dataset,
    }

    # Never cache errors (frozen design Section 18) — by this point any
    # exception has already propagated and skipped this line, so reaching
    # here means we always have a real result (ok / no_data / low_confidence).
    cache.set(cache_key, result)

    return result