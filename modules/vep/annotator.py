"""
modules.vep.annotator
========================

The public entrypoint for the VEP module: ``annotate(chrom, position,
reference, alternate)``. This is the only function other modules /
the pipeline integration layer should ever import from ``modules.vep``.

Orchestration only — validation, cache lookup, the REST call, parsing,
and the reference-resource status check are each implemented elsewhere
(``shared.validators``, ``modules.vep.client``, ``modules.vep.parser``,
``shared.reference``); this file wires them together in the order
frozen by the engineering contract (3A §3.2):

    validate -> check cache -> call API -> parse -> wrap -> cache -> return
"""

from __future__ import annotations

import time
from typing import Any, Optional

from shared.cache import DiskCache, MemoryCache, make_key
from shared.config import get_config
from shared.exceptions import AnnotationUnavailableError, CacheError
from shared.logging import get_logger
from shared.reference import ResourceStatus, get_reference_manager
from shared.validators import validate_variant

from modules.vep.client import EnsemblVepClient
from modules.vep.constants import CACHE_TTL_SECONDS, STATUS_CACHE_HIT, STATUS_OK
from modules.vep.models import VEPAnnotation, build_output_envelope
from modules.vep.parser import parse_vep_record

log = get_logger(__name__)

MODULE_NAME = "vep"

# Process-wide L1 cache for repeated lookups within a single run, in
# front of the cross-run DiskCache (3A §3.2 / O-3). Module-level so it
# survives across calls within one process but never across processes.
_memory_cache = MemoryCache(default_ttl_seconds=CACHE_TTL_SECONDS)


def reset_memory_cache_for_testing() -> None:
    """Test-only helper to clear the module-level L1 cache and the
    once-per-process reference-status flag between test cases, mirroring
    ``shared.config.reset_config_for_testing()``.
    """
    global _reference_status_logged
    _memory_cache.clear()
    _reference_status_logged = False


def _get_pinned_ensembl_release() -> Optional[str]:
    """The Ensembl release used to stamp every annotation's provenance.

    This is read from ``shared.config``'s pinned ``versions.ensembl_release``
    rather than from ``shared.reference`` — see the module README
    ("Reference Manager integration") for why: the ``ensembl`` resource
    declared in ``shared.config.reference_resources`` describes a local
    GTF file used for *offline* annotation, which this REST-based module
    never reads. Gating every REST annotation on that unrelated local
    file being present on disk would be incorrect coupling. The Reference
    Manager is still consulted (see ``_log_reference_resource_status``)
    purely for diagnostic visibility, never as a hard dependency.
    """
    cfg = get_config()
    return cfg.version("ensembl_release")


_reference_status_logged = False


def _log_reference_resource_status() -> None:
    """Best-effort, non-fatal visibility into the local 'ensembl' shared
    reference resource's status, satisfying the "query the Reference
    Manager at module init" requirement (3A §3.2) without making this
    REST-based module depend on a local GTF it never reads.

    Runs at most once per process — ``ReferenceManager.verify()`` walks
    every declared resource's directory on disk, so calling it on every
    ``annotate()`` invocation would add needless filesystem I/O to the
    hot path for a check that is purely informational.
    """
    global _reference_status_logged
    if _reference_status_logged:
        return
    _reference_status_logged = True
    try:
        rm = get_reference_manager()
        report = next(
            (r for r in rm.verify() if r.name == "ensembl"), None
        )
        if report is not None and report.status != ResourceStatus.INSTALLED:
            log.info(
                "local 'ensembl' reference resource is %s (informational "
                "only — modules.vep uses the live Ensembl REST API and "
                "does not read this local resource)",
                report.status.value,
                extra={"resource": "ensembl", "status": report.status.value},
            )
    except Exception as exc:  # pragma: no cover - diagnostics must never break annotate()
        log.warning(
            "reference manager status check failed (non-fatal)",
            extra={"error": str(exc)},
        )


def _disk_cache() -> DiskCache:
    cfg = get_config()
    return DiskCache(
        cfg.cache_dir / "ensembl_vep.sqlite",
        default_ttl_seconds=CACHE_TTL_SECONDS,
    )


def annotate(
    chrom: str,
    position: int,
    reference: str,
    alternate: str,
) -> dict[str, Any]:
    """Annotate a single GRCh38 SNV with Ensembl VEP structural
    consequence data.

    Returns the standard framework output envelope::

        {
            "variant_id": "11:5227002:T:A",
            "module_name": "vep",
            "status": "ok" | "no_data" | "cache_hit",
            "fields": {...VEPAnnotation.to_dict()...},
            "source_version": "<pinned ensembl release>",
        }

    Raises:
        ValidationError: malformed chrom/position/allele input, or a
            non-SNV (multi-allelic/indel) variant.
        AnnotationUnavailableError: Ensembl has no data for this locus.
        NetworkError / RateLimitError: the API is unreachable or rate
            limited beyond the configured retry budget.

    Never raises a generic ``Exception`` for an annotation failure —
    every error surfaces as a ``shared.exceptions.FrameworkError``
    subclass, per the frozen error-handling contract.
    """
    variant = validate_variant(chrom, position, reference, alternate)
    ensembl_release = _get_pinned_ensembl_release()
    _log_reference_resource_status()

    cache_key = make_key("vep", "GRCh38", ensembl_release, variant.variant_id)

    # L1: in-process memory cache.
    cached = _memory_cache.get(cache_key)
    if cached is not None:
        log.debug("vep memory cache hit", extra={"variant": variant.variant_id})
        return {**cached, "status": STATUS_CACHE_HIT}

    # L2: cross-run disk cache. A CacheError on read must not crash the
    # module (3A §11.2) — log and fall through to the API.
    disk_cache = _disk_cache()
    try:
        cached = disk_cache.get(cache_key)
    except CacheError as exc:
        log.warning(
            "disk cache read failed; falling through to API",
            extra={"variant": variant.variant_id, "error": str(exc)},
        )
        cached = None

    if cached is not None:
        log.debug("vep disk cache hit", extra={"variant": variant.variant_id})
        _memory_cache.set(cache_key, cached)
        return {**cached, "status": STATUS_CACHE_HIT}

    log.info(
        "annotating variant",
        extra={"variant": variant.variant_id, "module_name": MODULE_NAME},
    )

    start = time.monotonic()
    try:
        with EnsemblVepClient() as client:
            raw_record = client.fetch_raw_annotation(variant)
    except AnnotationUnavailableError:
        # Per 3A §11.1: error responses are never cached.
        log.info(
            "no annotation available",
            extra={"variant": variant.variant_id},
        )
        raise

    annotation: VEPAnnotation = parse_vep_record(
        raw_record, variant=variant, ensembl_release=ensembl_release
    )

    envelope = build_output_envelope(
        variant_id=variant.variant_id,
        status=STATUS_OK,
        annotation=annotation,
        ensembl_release=ensembl_release,
    )

    elapsed_ms = round((time.monotonic() - start) * 1000, 2)
    log.info(
        "annotation complete",
        extra={
            "variant": variant.variant_id,
            "duration_ms": elapsed_ms,
            "transcript_source": annotation.transcript_source,
            "most_severe_consequence": annotation.most_severe_consequence,
        },
    )

    # Cache the raw API response separately for future access (3A §10.2)
    # and the parsed output envelope for normal consumption. Never cache
    # on error (handled above by letting AnnotationUnavailableError
    # propagate before reaching this point).
    try:
        disk_cache.set(make_key("vep_raw", variant.variant_id, ensembl_release), raw_record)
        disk_cache.set(cache_key, envelope)
    except CacheError as exc:
        log.warning(
            "disk cache write failed; annotation succeeded regardless",
            extra={"variant": variant.variant_id, "error": str(exc)},
        )

    _memory_cache.set(cache_key, envelope)

    return envelope