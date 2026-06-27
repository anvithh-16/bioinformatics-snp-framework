import pytest
import responses

from shared.exceptions import AnnotationUnavailableError, NetworkError, RateLimitError, ValidationError
from shared.http import HttpClient
from shared.validators import validate_variant

from modules.vep.client import EnsemblVepClient
from modules.vep.annotator import annotate

from .conftest import load_fixture

BASE_URL = "https://rest.ensembl.org"


def _test_http_client(max_retries: int = 2) -> HttpClient:
    """A real HttpClient pointed at the live Ensembl base URL but with a
    very high rate limit and small retry budget, so mock REST tests stay
    fast and deterministic regardless of the configured production
    rate-limit/retry settings.
    """
    return HttpClient(
        service_name="ensembl_vep_test",
        base_url=BASE_URL,
        timeout_seconds=5,
        max_retries=max_retries,
        rate_limit_per_second=10_000,
    )


@responses.activate
def test_full_response_parsing_via_client():
    fixture = load_fixture("vep_response_hbb.json")
    responses.add(
        responses.GET,
        f"{BASE_URL}/vep/human/region/11:5227002-5227002:1/A",
        json=fixture,
        status=200,
    )
    client = EnsemblVepClient(http_client=_test_http_client())
    variant = validate_variant("11", 5227002, "T", "A")
    raw = client.fetch_raw_annotation(variant)
    assert raw["most_severe_consequence"] == "missense_variant"

    # Required params (3A §4.2 / I-1 / I-3) were actually sent.
    sent_url = responses.calls[0].request.url
    for param in ("hgvs=1", "mane_select=1", "canonical=1", "numbers=1"):
        assert param in sent_url
    # The prototype's incorrect content-type query param must not appear.
    assert "content-type" not in sent_url


@responses.activate
def test_empty_list_response_raises_annotation_unavailable():
    responses.add(
        responses.GET,
        f"{BASE_URL}/vep/human/region/8:144500000-144500000:1/G",
        json=[],
        status=200,
    )
    client = EnsemblVepClient(http_client=_test_http_client())
    variant = validate_variant("8", 144500000, "A", "G")
    with pytest.raises(AnnotationUnavailableError):
        client.fetch_raw_annotation(variant)


@responses.activate
def test_400_raises_annotation_unavailable():
    responses.add(
        responses.GET,
        f"{BASE_URL}/vep/human/region/1:99999999999-99999999999:1/G",
        json={"error": "position out of bounds"},
        status=400,
    )
    client = EnsemblVepClient(http_client=_test_http_client())
    variant = validate_variant("1", 99999999999, "A", "G")
    with pytest.raises(AnnotationUnavailableError):
        client.fetch_raw_annotation(variant)


@responses.activate
def test_404_raises_annotation_unavailable():
    responses.add(
        responses.GET,
        f"{BASE_URL}/vep/human/region/1:100-100:1/G",
        json={}, status=404,
    )
    client = EnsemblVepClient(http_client=_test_http_client())
    variant = validate_variant("1", 100, "A", "G")
    with pytest.raises(AnnotationUnavailableError):
        client.fetch_raw_annotation(variant)


@responses.activate
def test_5xx_raises_network_error_after_retries():
    url = f"{BASE_URL}/vep/human/region/1:100-100:1/G"
    for _ in range(3):
        responses.add(responses.GET, url, status=503)
    client = EnsemblVepClient(http_client=_test_http_client(max_retries=2))
    variant = validate_variant("1", 100, "A", "G")
    with pytest.raises(NetworkError):
        client.fetch_raw_annotation(variant)
    assert len(responses.calls) == 3


@responses.activate
def test_retry_on_500_then_success():
    url = f"{BASE_URL}/vep/human/region/11:5227002-5227002:1/A"
    fixture = load_fixture("vep_response_hbb.json")
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, json=fixture, status=200)
    client = EnsemblVepClient(http_client=_test_http_client(max_retries=4))
    variant = validate_variant("11", 5227002, "T", "A")
    raw = client.fetch_raw_annotation(variant)
    assert raw["most_severe_consequence"] == "missense_variant"
    assert len(responses.calls) == 3


@responses.activate
def test_rate_limit_429_eventually_raises():
    url = f"{BASE_URL}/vep/human/region/1:100-100:1/G"
    for _ in range(3):
        responses.add(responses.GET, url, status=429)
    client = EnsemblVepClient(http_client=_test_http_client(max_retries=2))
    variant = validate_variant("1", 100, "A", "G")
    with pytest.raises(RateLimitError):
        client.fetch_raw_annotation(variant)


def test_indel_input_rejected_before_any_api_call():
    client = EnsemblVepClient(http_client=_test_http_client())
    variant = validate_variant("17", 43057051, "C", "CA")
    with pytest.raises(ValidationError):
        client.fetch_raw_annotation(variant)


# ---------------------------------------------------------------------------
# End-to-end annotate() tests using the real shared.http.HttpClient.for_service
# pathway (mocked at the responses layer, never hitting the real network).
# ---------------------------------------------------------------------------

@responses.activate
def test_annotate_end_to_end_ok():
    fixture = load_fixture("vep_response_hbb.json")
    responses.add(
        responses.GET,
        f"{BASE_URL}/vep/human/region/11:5227002-5227002:1/A",
        json=fixture,
        status=200,
    )
    result = annotate("11", 5227002, "T", "A")
    assert result["status"] == "ok"
    assert result["module_name"] == "vep"
    assert result["source_version"] == "113"
    assert result["fields"]["gene_symbol"] == "HBB"
    assert result["fields"]["transcript_source"] == "mane_select"


def test_annotate_rejects_invalid_chrom_before_any_http():
    with pytest.raises(ValidationError):
        annotate("chrZZZ", 100, "A", "G")