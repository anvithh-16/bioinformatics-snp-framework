"""
modules/gnomad/client.py

GnomadRemoteClient — the GraphQL backend for the gnomAD module.

This is the ONLY file in the module that issues network requests. It is a
thin, testable wrapper around `shared.http.HttpClient`: build the GraphQL
request body, send it, validate the transport-level response, and hand
back the raw JSON `data` payload. It does not interpret biological
meaning of any field — that is `parser.py`'s job (mirrors the separation
already established by VEP's client.py / region_map.py split).

Per the frozen design (gnomAD_Module_Design.md Section 9), this client is
one of two interchangeable backends behind `annotate()`. The local
Tabix/VCF backend (`GnomadLocalClient`) is explicitly out of scope for
this conversation. To keep that future addition a non-breaking change,
this class exposes exactly one method — `fetch_variant_data()` — that a
future `GnomadLocalClient` would also need to implement with the same
signature, even though its internals would read a local index instead of
calling an API.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from shared.http import HttpClient
from shared.logging import get_logger
from shared.exceptions import AnnotationUnavailableError, NetworkError

from .constants import VARIANT_QUERY

log = get_logger(__name__)


class GnomadRemoteClient:
    """
    Thin GraphQL client for the gnomAD public API.

    Construction does not perform any I/O. `HttpClient.for_service("gnomad")`
    reads `services.gnomad` from config.yaml (base_url, timeout_seconds,
    max_retries, rate_limit_per_second) — this class never hardcodes any of
    those values, per the framework rule (PROJECT_CONTEXT.md / VEP Defect
    C-8) that no module may bypass `shared.config`.
    """

    def __init__(self) -> None:
        self._http = HttpClient.for_service("gnomad")

    def fetch_variant_data(
        self, variant_id: str, dataset: str
    ) -> Optional[Dict[str, Any]]:
        """
        Execute the pinned GraphQL variant query for one gnomAD-notation
        variant_id (e.g. "1-55051215-G-A") against the given pinned
        `dataset` (e.g. "gnomad_r4").

        Returns the raw `data.variant` object (a dict) on success, or
        `None` if gnomAD has no record for this variant (a valid,
        expected outcome — NOT an error).

        Raises:
            AnnotationUnavailableError: the GraphQL response itself
                reported an `errors` array (e.g. malformed variant_id
                rejected by gnomAD's own validation). This is distinct
                from "not found": gnomAD explicitly told us the query
                was rejected, vs. silently returning a null variant.
            NetworkError: transport-level failure. In practice this is
                raised internally by HttpClient after exhausting
                `max_retries`; it is allowed to propagate unchanged.
        """
        body = {
            "query": VARIANT_QUERY,
            "variables": {"variantId": variant_id, "dataset": dataset},
        }

        log.info(
            "Querying gnomAD GraphQL API",
            extra={"variant_id": variant_id, "dataset": dataset},
        )

        response = self._http.post("", json_body=body)
        response.raise_for_status()

        payload = response.json_body or {}

        graphql_errors = payload.get("errors")
        if graphql_errors:
            message = graphql_errors[0].get("message", "Unknown GraphQL error")
            raise AnnotationUnavailableError(
                f"gnomAD GraphQL API returned an error: {message}",
                context={
                    "variant_id": variant_id,
                    "dataset": dataset,
                    "graphql_errors": graphql_errors,
                },
            )

        data = payload.get("data") or {}
        variant_data = data.get("variant")

        if variant_data is None:
            log.info(
                "Variant not found in gnomAD",
                extra={"variant_id": variant_id, "dataset": dataset},
            )
            return None

        return variant_data