"""
modules/gnomad/tests/test_client_mocked.py

Tests GnomadRemoteClient against mocked HTTP responses using the
`responses` library (the same approach shared/tests/ already uses for
HttpClient, per Shared_README.md's testing section: "All HTTP tests use
the `responses` library to mock external calls — no test ever makes a
real network request.").

These tests cover the client.py layer specifically: request construction,
GraphQL `errors` handling, and the "not found" (`variant: null`) path.
Higher-level behavior (caching, full annotate() envelope) is covered in
test_cache.py and test_unit.py respectively.
"""

import json
import re
from pathlib import Path

import pytest
import responses

from shared.exceptions import AnnotationUnavailableError

from modules.gnomad.client import GnomadRemoteClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Matched via regex rather than an exact string. Confirmed against a real
# run of this test suite inside the actual project (not this module's own
# assumption): shared.http.HttpClient.for_service("gnomad").post("", ...)
# produces a request to "https://gnomad.broadinstitute.org/api/" (note the
# trailing slash) even though the configured base_url has none. That
# behavior lives entirely inside shared/http/client.py's URL-joining logic,
# which this module does not own and must not change (Project_Context.md:
# "No module should force changes to the shared infrastructure"). The test
# was the side that had assumed an exact, slash-less URL -- that assumption
# was wrong, not the implementation. Matching `/api/?$` makes this test
# correct regardless of whether HttpClient's trailing-slash behavior is
# present or absent, so it won't silently re-break if that detail changes.
GNOMAD_BASE_URL = re.compile(r"^https://gnomad\.broadinstitute\.org/api/?$")


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class TestGnomadRemoteClientFetchVariantData:
    @responses.activate
    def test_found_variant_returns_raw_variant_dict(self):
        fixture = _load_fixture("gnomad_response_found.json")
        responses.add(responses.POST, GNOMAD_BASE_URL, json=fixture, status=200)

        client = GnomadRemoteClient()
        result = client.fetch_variant_data("1-55051215-G-A", "gnomad_r4")

        assert result is not None
        assert result["variant_id"] == "1-55051215-G-A"
        assert result["exome"]["ac"] == 12

    @responses.activate
    def test_not_found_variant_returns_none(self):
        fixture = _load_fixture("gnomad_response_not_found.json")
        responses.add(responses.POST, GNOMAD_BASE_URL, json=fixture, status=200)

        client = GnomadRemoteClient()
        result = client.fetch_variant_data("99-1-A-T", "gnomad_r4")

        assert result is None

    @responses.activate
    def test_graphql_error_raises_annotation_unavailable(self):
        fixture = _load_fixture("gnomad_response_error.json")
        responses.add(responses.POST, GNOMAD_BASE_URL, json=fixture, status=200)

        client = GnomadRemoteClient()
        with pytest.raises(AnnotationUnavailableError):
            client.fetch_variant_data("not-a-real-id", "gnomad_r4")

    @responses.activate
    def test_request_body_includes_pinned_dataset_and_variant_id(self):
        fixture = _load_fixture("gnomad_response_found.json")
        responses.add(responses.POST, GNOMAD_BASE_URL, json=fixture, status=200)

        client = GnomadRemoteClient()
        client.fetch_variant_data("1-55051215-G-A", "gnomad_r4")

        sent_body = json.loads(responses.calls[0].request.body)
        assert sent_body["variables"]["variantId"] == "1-55051215-G-A"
        assert sent_body["variables"]["dataset"] == "gnomad_r4"
        assert "query" in sent_body

    @responses.activate
    def test_http_error_status_propagates(self):
        responses.add(
            responses.POST,
            GNOMAD_BASE_URL,
            json={"error": "internal server error"},
            status=500,
        )

        client = GnomadRemoteClient()
        with pytest.raises(Exception):
            # HttpClient's retry/backoff will exhaust retries against the
            # mocked 500 and raise (NetworkError per shared.http contract);
            # exact exception type is shared infra's responsibility, this
            # test only asserts the client does not silently swallow it.
            client.fetch_variant_data("1-55051215-G-A", "gnomad_r4")