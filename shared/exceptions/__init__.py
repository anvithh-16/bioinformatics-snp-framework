"""
shared.exceptions
==================

Unified exception hierarchy for the entire annotation framework.

Design principle
-----------------
Every future module (VEP, AlphaMissense, gnomAD, GERP++, LOEUF, InterVar,
SpliceAI, MutPred, AlphaFold+DynaMut2, GTEx, STRING, GWAS Catalog) must raise
ONLY exceptions defined here (or subclasses of them defined in this file).
No module should ever define its own ad-hoc exception classes — this is
what lets the integration layer (built after all 12 modules exist) catch
errors generically without knowing which module raised them.

All exceptions carry an optional `context: dict` so callers can attach
structured debugging info (e.g. {"variant": "1:12345:A:G", "service": "VEP"})
without subclassing further.
"""

from __future__ import annotations
from typing import Any, Optional


class FrameworkError(Exception):
    """Base class for every exception raised anywhere in this framework.

    Catching FrameworkError at the top of an integration loop guarantees
    no unexpected exception type escapes a module call.
    """

    def __init__(self, message: str, *, context: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            return f"{self.message} | context={self.context}"
        return self.message


# ---------------------------------------------------------------------------
# Network / HTTP layer
# ---------------------------------------------------------------------------

class NetworkError(FrameworkError):
    """Raised when an HTTP request fails after all retries are exhausted.

    Used by: shared.http.client for every REST-based module
    (VEP, AlphaMissense, gnomAD, SpliceAI, STRING, GWAS Catalog, GTEx).
    """


class RateLimitError(NetworkError):
    """Raised when a service's rate limit is hit and cannot be resolved
    by waiting (e.g. server returns 429 repeatedly past max retries).
    """


class TimeoutError_(NetworkError):
    """Raised when a request exceeds its configured timeout.

    Named with a trailing underscore to avoid shadowing the builtin
    TimeoutError while keeping naming consistent with the rest of the
    hierarchy.
    """


# ---------------------------------------------------------------------------
# Annotation-level errors (generic — no biology-specific subclasses here)
# ---------------------------------------------------------------------------

class AnnotationUnavailableError(FrameworkError):
    """Raised when a module cannot produce an annotation for a given
    variant/gene — e.g. no data at this locus, optional tool not installed,
    or the upstream service returned an empty result.

    This is NOT an error in the traditional sense for optional (Tier 3)
    modules — callers should catch this and record `status="no_data"` or
    `status="unavailable"` rather than letting the pipeline crash.
    """


class OptionalModuleUnavailableError(AnnotationUnavailableError):
    """Raised specifically when a Tier 3 (optional) module's underlying
    tool is not installed/configured (e.g. MutPred2 binary missing).

    The integration layer must catch this and continue the pipeline —
    per the finalized architecture, optional modules must never break
    the pipeline.
    """


# ---------------------------------------------------------------------------
# Configuration layer
# ---------------------------------------------------------------------------

class ConfigurationError(FrameworkError):
    """Raised when configuration is missing, malformed, or inconsistent
    (e.g. a required env var is unset, a YAML config fails schema
    validation, or a referenced directory does not exist).
    """


# ---------------------------------------------------------------------------
# Validation layer
# ---------------------------------------------------------------------------

class ValidationError(FrameworkError):
    """Raised by shared.validators when input fails validation
    (e.g. malformed chromosome name, invalid allele, ambiguous genome
    build). Every module's `annotate()` entrypoint should validate inputs
    via shared.validators before doing any work, and let this propagate
    rather than producing a partial/garbage annotation.
    """


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------

class CacheError(FrameworkError):
    """Raised when the cache layer fails in a way that should not be
    silently swallowed (e.g. disk cache directory not writable, corrupt
    cache entry that fails deserialization).

    Note: a cache MISS is not an error and must never raise this.
    """


# ---------------------------------------------------------------------------
# Reference resource layer (shared.reference — Tier-0.5)
# ---------------------------------------------------------------------------

class ResourceError(FrameworkError):
    """Base class for errors raised by shared.reference.ReferenceManager.

    The Reference Manager only inspects and reports on shared biological
    resources (GRCh38, ClinVar, Ensembl, dbNSFP, UniProt, gnomAD,
    SpliceAI, AlphaFold cache) — it never downloads or deletes anything.
    These exceptions cover failures in that inspection/reporting role,
    not biological-data problems (those belong to the modules that
    consume the resources, once they exist).
    """


class UnknownResourceError(ResourceError):
    """Raised when code asks the Reference Manager for a resource name
    that isn't declared in shared.config's `reference_resources` block
    (e.g. a typo, or a module written against a future resource that
    hasn't been added to config yet).
    """


class ResourceCorruptedError(ResourceError):
    """Raised by `ReferenceManager.get()` when a resource's on-disk state
    is internally inconsistent in a way that makes it unsafe to hand to
    a calling module — e.g. its directory exists but a required marker
    file is unreadable, or a manifest fails to parse. A plain MISSING or
    EMPTY resource does NOT raise this; only a resource that is partially
    present in a broken way does. `verify()` and `summary()` report this
    state without raising — only `get()` raises, since `get()` is the
    call a module makes when it actually needs to use the resource.
    """
