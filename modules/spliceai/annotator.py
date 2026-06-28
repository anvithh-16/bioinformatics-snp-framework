from __future__ import annotations

from shared.cache import DiskCache, make_key
from shared.config import get_config
from shared.exceptions import ValidationError
from shared.logging import get_logger
from shared.validators import validate_variant

from modules.spliceai.client import SpliceAILocalClient
from modules.spliceai.constants import (
    CACHE_FILENAME,
    CACHE_TTL_SECONDS,
    MODULE_NAME,
)
from modules.spliceai.models import SpliceAIAnnotation
from modules.spliceai.parser import parse_variant_rows

log = get_logger(__name__)

_VERSION_KEY = "spliceai_version"


def _get_cache(cfg) -> DiskCache:
    return DiskCache(cfg.cache_dir / CACHE_FILENAME, default_ttl_seconds=CACHE_TTL_SECONDS)


def annotate(
    chrom: str,
    position: int,
    reference: str,
    alternate: str,
    client: SpliceAILocalClient = None,
) -> dict:
    """
    Canonical module entrypoint. Looks up the queried SNV directly by
    genomic coordinate against the pinned local SpliceAI masked SNV file,
    independent of any other module's transcript selection.

    Returns the standard annotation envelope. Raises ValidationError for
    bad input or an unpinned spliceai_version. Raises
    UnknownResourceError / ResourceCorruptedError if the local resource
    is missing, unindexed, or corrupted. A variant simply not present in
    the dataset (outside Illumina's scored window, or scored for other
    alleles only) is not an error and is reported as status='no_data'.
    """
    variant = validate_variant(chrom, position, reference, alternate)

    if len(variant.reference) != 1 or len(variant.alternate) != 1:
        raise ValidationError(
            "SpliceAI supports only SNVs in v1.",
            context={
                "reference": variant.reference,
                "alternate": variant.alternate,
            },
        )

    cfg = get_config()

    spliceai_version = cfg.version(_VERSION_KEY)
    if spliceai_version is None:
        raise ValidationError(
            f"'{_VERSION_KEY}' is not pinned in config.yaml. "
            "Pin the version before running SpliceAI annotations to ensure "
            "reproducibility (see config.yaml versions block).",
            context={"version_key": _VERSION_KEY},
        )

    spliceai_client = client or SpliceAILocalClient()
    data_release = spliceai_version

    cache = _get_cache(cfg)
    cache_key = make_key(MODULE_NAME, "local", data_release, variant.chrom, variant.position, variant.reference, variant.alternate)

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    rows = spliceai_client.fetch_variant_rows(variant.chrom, variant.position)
    parsed = parse_variant_rows(rows, variant.alternate)

    if parsed is None:
        annotation = SpliceAIAnnotation.no_data(variant.variant_id, data_release)
    else:
        annotation = SpliceAIAnnotation.from_parsed(
            variant_id=variant.variant_id,
            data_release=data_release,
            ds_ag=parsed["ds_ag"],
            ds_al=parsed["ds_al"],
            ds_dg=parsed["ds_dg"],
            ds_dl=parsed["ds_dl"],
            dp_ag=parsed["dp_ag"],
            dp_al=parsed["dp_al"],
            dp_dg=parsed["dp_dg"],
            dp_dl=parsed["dp_dl"],
            gene_symbol=parsed["symbol"],
        )

    envelope = annotation.to_envelope()
    cache.set(cache_key, envelope)
    return envelope