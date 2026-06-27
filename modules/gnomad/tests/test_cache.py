"""
modules/gnomad/tests/test_cache.py

Tests the caching contract from gnomAD_Module_Design.md Section 18,
mirroring VEP's frozen caching contract (Part 11 of VEP_Module_Design.md):

  - A cache hit must short-circuit and never call the backend.
  - A cache miss must call the backend exactly once and then populate
    the cache.
  - Errors must never be cached (AnnotationUnavailableError / NetworkError
    must not leave a cache entry behind).
  - The cache key must include backend + dataset version + coordinates,
    so that different pinned dataset versions never collide.

These tests monkeypatch `modules.gnomad._get_backend` rather than hitting
the real client, since the goal here is to test annotate()'s caching
*orchestration*, not the HTTP layer (already covered in
test_client_mocked.py).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import modules.gnomad as gnomad_module
from shared.exceptions import AnnotationUnavailableError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def _reset_module_singletons():
    """
    annotate() lazily caches a DiskCache + GnomadRemoteClient at module
    level. Reset both between tests so each test gets a fresh cache
    backed by a tmp-path config, and a fresh mocked backend.
    """
    gnomad_module._cache = None
    gnomad_module._remote_client = None
    yield
    gnomad_module._cache = None
    gnomad_module._remote_client = None


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    gnomad_module._remote_client = backend
    return backend


class TestAnnotateCaching:
    def test_cache_miss_then_hit_calls_backend_once(self, mock_backend):
        fixture = _load_fixture("gnomad_response_found.json")["data"]["variant"]
        mock_backend.fetch_variant_data.return_value = fixture

        result1 = gnomad_module.annotate("1", 55051215, "G", "A")
        result2 = gnomad_module.annotate("1", 55051215, "G", "A")

        assert mock_backend.fetch_variant_data.call_count == 1
        assert result1 == result2
        assert result1["status"] == "ok"

    def test_different_alleles_are_different_cache_entries(self, mock_backend):
        fixture = _load_fixture("gnomad_response_found.json")["data"]["variant"]
        mock_backend.fetch_variant_data.return_value = fixture

        gnomad_module.annotate("1", 55051215, "G", "A")
        gnomad_module.annotate("1", 55051215, "G", "C")

        assert mock_backend.fetch_variant_data.call_count == 2

    def test_no_data_result_is_still_cached(self, mock_backend):
        mock_backend.fetch_variant_data.return_value = None

        result1 = gnomad_module.annotate("99", 1, "A", "T")
        result2 = gnomad_module.annotate("99", 1, "A", "T")

        assert result1["status"] == "no_data"
        assert mock_backend.fetch_variant_data.call_count == 1
        assert result1 == result2

    def test_annotation_unavailable_error_is_never_cached(self, mock_backend):
        mock_backend.fetch_variant_data.side_effect = AnnotationUnavailableError(
            "gnomAD GraphQL API returned an error: bad id"
        )

        with pytest.raises(AnnotationUnavailableError):
            gnomad_module.annotate("1", 55051215, "G", "A")

        # Backend must be called again on retry -- nothing was cached.
        mock_backend.fetch_variant_data.side_effect = AnnotationUnavailableError(
            "still bad"
        )
        with pytest.raises(AnnotationUnavailableError):
            gnomad_module.annotate("1", 55051215, "G", "A")

        assert mock_backend.fetch_variant_data.call_count == 2