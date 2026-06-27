import pytest
import responses

from shared.config import FrameworkConfig, reset_config_for_testing
from shared.http.client import HttpClient
from shared.exceptions import NetworkError


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Point config at a temp project root so tests never touch real
    project directories, and reset the rate-limiter registry between
    tests implicitly via a fresh service name where needed.
    """
    reset_config_for_testing()
    monkeypatch.setenv("FRAMEWORK_PROJECT_ROOT", str(tmp_path))
    yield
    reset_config_for_testing()


def _test_client() -> HttpClient:
    return HttpClient(
        service_name="test_service",
        base_url="https://example-bio-api.test",
        timeout_seconds=5,
        max_retries=2,
        rate_limit_per_second=1000,  # don't let rate limiting slow tests
    )


@responses.activate
def test_get_success_parses_json():
    responses.add(
        responses.GET,
        "https://example-bio-api.test/variant/1:100:A:G",
        json={"consequence": "missense_variant"},
        status=200,
    )
    client = _test_client()
    resp = client.get("variant/1:100:A:G")
    assert resp.status_code == 200
    assert resp.json_body == {"consequence": "missense_variant"}


@responses.activate
def test_5xx_is_retried_then_raises():
    responses.add(responses.GET, "https://example-bio-api.test/flaky", status=503)
    responses.add(responses.GET, "https://example-bio-api.test/flaky", status=503)
    responses.add(responses.GET, "https://example-bio-api.test/flaky", status=503)
    client = _test_client()
    with pytest.raises(NetworkError):
        client.get("flaky")
    assert len(responses.calls) == 3  # initial + 2 retries (max_retries=2)


@responses.activate
def test_eventual_success_after_retry():
    responses.add(responses.GET, "https://example-bio-api.test/recovers", status=503)
    responses.add(
        responses.GET,
        "https://example-bio-api.test/recovers",
        json={"ok": True},
        status=200,
    )
    client = _test_client()
    resp = client.get("recovers")
    assert resp.status_code == 200
    assert resp.json_body == {"ok": True}


@responses.activate
def test_404_does_not_retry_but_raises_on_raise_for_status():
    responses.add(
        responses.GET, "https://example-bio-api.test/missing", status=404, json={}
    )
    client = _test_client()
    resp = client.get("missing")
    assert resp.status_code == 404
    with pytest.raises(NetworkError):
        resp.raise_for_status()
    assert len(responses.calls) == 1  # 4xx (other than 429) is not retried
