from __future__ import annotations

from shared.cache import DiskCache, make_key
from shared.config import get_config
from shared.logging import get_logger
from shared.validators import validate_variant
from shared.exceptions import ValidationError

from modules.alphamissense.client import AlphaMissenseClient
from modules.alphamissense.constants import CACHE_FILENAME, CACHE_TTL_SECONDS, MODULE_NAME
from modules.alphamissense.models import AlphaMissenseAnnotation
from modules.alphamissense.parser import parse_matching_rows

log = get_logger(__name__)


def _get_cache(cfg) -> DiskCache:
    return DiskCache(cfg.cache_dir / CACHE_FILENAME, default_ttl_seconds=CACHE_TTL_SECONDS)


def _build_annotation(variant_id: str, candidates: list, data_release) -> AlphaMissenseAnnotation:
    if len(candidates) == 0:
        return AlphaMissenseAnnotation.no_data(variant_id, data_release)
    if len(candidates) == 1:
        return AlphaMissenseAnnotation.single_match(variant_id, candidates[0], data_release)
    return AlphaMissenseAnnotation.multiple_matches(variant_id, candidates, data_release)


def annotate(
    chrom: str,
    position: int,
    reference: str,
    alternate: str,
    client: AlphaMissenseClient = None,
) -> dict:
    """
    Canonical module entrypoint. Looks up the queried SNV directly by
    genomic coordinate against the pinned local AlphaMissense_hg38
    file, independent of any other module's transcript selection.

    Returns the standard annotation envelope. Raises only for genuine
    setup/infrastructure problems (ValidationError on bad input;
    UnknownResourceError/ResourceCorruptedError if the local resource
    is missing, unindexed, or corrupted). A variant simply not present
    in the dataset is not an error and is reported via
    status="no_data" in the returned envelope, not an exception —
    this is a deterministic, reproducible outcome against a static
    local file, not a possibly-transient API response.
    """
    variant = validate_variant(chrom, position, reference, alternate)
    if len(variant.reference) != 1 or len(variant.alternate) != 1:
        raise ValidationError(
            "AlphaMissense supports only SNVs.",
            context={
                "reference": variant.reference,
                "alternate": variant.alternate,
            },
        )

    cfg = get_config()
    am_client = client or AlphaMissenseClient()
    data_release = am_client.version

    cache = _get_cache(cfg)
    cache_key = make_key(MODULE_NAME, data_release, variant.variant_id)

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    raw_rows = am_client.fetch_raw_rows(variant.chrom, variant.position)
    candidates = parse_matching_rows(raw_rows, variant.reference, variant.alternate)

    annotation = _build_annotation(variant.variant_id, candidates, data_release)
    envelope = annotation.to_envelope()

    cache.set(cache_key, envelope)
    return envelope