"""
modules.vep.client
=====================

Thin REST integration layer for the Ensembl VEP API. This module owns
*only* request construction and the raw HTTP call — it does not parse
biology, select transcripts, or build VEPAnnotation objects (that's
``modules.vep.parser``).

Per the frozen engineering contract (3A §3.2 / §3.3), this is the ONLY
place in the module that talks to ``shared.http``. No bare ``requests``
import appears anywhere in this module or any other file in
``modules/vep``.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.exceptions import AnnotationUnavailableError, ValidationError
from shared.http import HttpClient
from shared.logging import get_logger
from shared.validators import CanonicalVariant

from modules.vep.constants import REQUIRED_VEP_PARAMS

log = get_logger(__name__)

SERVICE_NAME = "ensembl_vep"


class EnsemblVepClient:
    """Wraps ``HttpClient.for_service("ensembl_vep")`` with the one
    endpoint shape this module needs: the VCF-notation region endpoint
    for a single GRCh38 SNV.

    A fresh ``HttpClient`` is constructed per ``EnsemblVepClient``
    instance (cheap — connection pooling lives inside the session, not
    across instances) so callers/tests can swap in
    ``HttpClient(...)`` directly without touching ``shared.config``.
    """

    def __init__(self, http_client: Optional[HttpClient] = None):
        self._client = http_client or HttpClient.for_service(SERVICE_NAME)

    def fetch_raw_annotation(self, variant: CanonicalVariant) -> dict[str, Any]:
        """Call the Ensembl VEP REST region endpoint for one SNV and
        return the single record's raw JSON dict (i.e. ``data[0]`` from
        the API's list-of-records response).

        Raises:
            ValidationError: the variant is not a single-nucleotide
                substitution (multi-allelic / indel) — the VCF-notation
                region endpoint used here is frozen for SNVs only (3A
                §4.1); indel support is a future consideration, not in
                scope for this module.
            AnnotationUnavailableError: the API returned an empty
                response, or a 400/404 indicating no data at this locus.
            NetworkError / RateLimitError: raised internally by
                ``shared.http.HttpClient`` after retries are exhausted;
                propagated unchanged.
        """
        self._validate_snv(variant)

        path = (
            f"vep/human/region/"
            f"{variant.chrom}:{variant.position}-{variant.position}:1/"
            f"{variant.alternate}"
        )

        response = self._client.get(path, params=dict(REQUIRED_VEP_PARAMS))

        if response.status_code in (400, 404):
            raise AnnotationUnavailableError(
                f"Ensembl VEP returned {response.status_code} for "
                f"{variant.variant_id} — no annotation available at this "
                "locus on GRCh38 (or the request was malformed).",
                context={
                    "variant": variant.variant_id,
                    "status_code": response.status_code,
                },
            )

        # raise_for_status() turns any other >=400 into NetworkError; 5xx
        # is already handled (raised as NetworkError) inside HttpClient
        # before this point, so this mainly guards stray 4xx codes.
        response.raise_for_status()

        body = response.json_body
        if not body or not isinstance(body, list) or len(body) == 0:
            raise AnnotationUnavailableError(
                "Ensembl VEP returned an empty response body for "
                f"{variant.variant_id}. This may mean the variant is "
                "intergenic, or it may indicate a malformed query — "
                "an empty response is never assumed to be a biological "
                "conclusion by this module.",
                context={"variant": variant.variant_id},
            )

        return body[0]

    @staticmethod
    def _validate_snv(variant: CanonicalVariant) -> None:
        if len(variant.reference) != 1 or len(variant.alternate) != 1:
            raise ValidationError(
                "modules.vep only supports single-nucleotide variants "
                f"via the VCF-notation region endpoint; got reference="
                f"{variant.reference!r}, alternate={variant.alternate!r}. "
                "Multi-allelic and indel variants must be decomposed "
                "upstream of this module.",
                context={
                    "reference": variant.reference,
                    "alternate": variant.alternate,
                },
            )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EnsemblVepClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()