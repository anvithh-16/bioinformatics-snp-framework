from __future__ import annotations

"""
Tests against the real downloaded Illumina SpliceAI masked SNV resource.

These tests are gated behind pytest.mark.integration and a module-level
skip guard: they are skipped automatically in CI and on any machine where
the real resource is not installed. They run only when explicitly
requested and the resource is present.

Run with:
    pytest modules/spliceai/tests/test_real_resource.py -m integration -v

IMPORTANT — autouse fixture override
--------------------------------------
conftest.py defines three autouse fixtures that patch get_reference_manager
and get_config for every test in this package. Tests in this file must
NOT inherit those patches — they need the real framework singletons.

This is achieved by re-patching them back to their real implementations
via explicit autouse fixtures scoped to this module only (using
`autouse=True` on a fixture defined here, which takes priority over
conftest.py's session/module/function-scoped autouse fixtures for tests
in this file).

The pattern mirrors the approach described in the pytest docs for
"overriding autouse fixtures in a subdirectory or file": a fixture
defined closer to the test (same file) shadows the one from conftest.py
when they share the same name.
"""

import pytest

import modules.spliceai.annotator as annotator_module
import modules.spliceai.client as client_module
from shared.exceptions import ResourceCorruptedError, UnknownResourceError
from shared.indexed_files import _reset_handle_cache_for_tests
from shared.reference import get_reference_manager as _real_get_reference_manager
from shared.config import get_config as _real_get_config

from modules.spliceai.annotator import annotate
from modules.spliceai.constants import STATUS_NO_DATA, STATUS_OK

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Undo the conftest.py autouse monkeypatches for every test in this file.
# These fixtures shadow conftest.py's autouse fixtures by sharing the
# same name and being defined in the same file as the tests that use them.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_reference_manager(monkeypatch):
    """
    Shadow conftest.py's fake_reference_manager with the real one.
    Tests in this file must talk to the real shared.reference singleton.
    """
    monkeypatch.setattr(
        client_module, "get_reference_manager", _real_get_reference_manager
    )
    # Return None — tests in this file do not use the fake manager object.
    return None


@pytest.fixture(autouse=True)
def _isolate_cache_dir(monkeypatch):
    """
    Shadow conftest.py's _isolate_cache_dir with the real config.
    Tests in this file use the real cache_dir from the project config.
    """
    monkeypatch.setattr(annotator_module, "get_config", _real_get_config)


@pytest.fixture(autouse=True)
def _reset_indexed_file_handles():
    yield
    _reset_handle_cache_for_tests()


# ---------------------------------------------------------------------------
# Module-level skip guard
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _require_real_resource():
    """Skip every test in this file if the real SpliceAI resource is
    not installed and usable under reference/spliceai/."""
    try:
        rm = _real_get_reference_manager()
        rm.get("spliceai")
    except (UnknownResourceError, ResourceCorruptedError) as exc:
        pytest.skip(f"Real SpliceAI resource not available: {exc}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_resource_resolves_without_error():
    """Smoke test: the resource manager can find and open the resource."""
    rm = _real_get_reference_manager()
    handle = rm.get("spliceai")
    assert handle is not None
    assert handle.version is not None


def test_known_scored_position_returns_ok_or_no_data():
    """
    Any query against a valid chromosome and position must return a
    well-formed envelope — never raise an unexpected exception.
    1:69090 is near OR4F5; it may or may not be scored in a given
    release, so we accept both ok and no_data.
    """
    result = annotate("1", 69090, "A", "T")
    assert result["status"] in (STATUS_OK, STATUS_NO_DATA)
    assert result["module_name"] == "spliceai"
    assert "fields" in result
    assert result["source_version"] is not None


def test_envelope_fields_always_present():
    """Every envelope, regardless of status, must carry all expected keys."""
    result = annotate("1", 69090, "A", "T")
    fields = result["fields"]
    expected_keys = {
        "ds_acceptor_gain", "ds_acceptor_loss", "ds_donor_gain", "ds_donor_loss",
        "dp_acceptor_gain", "dp_acceptor_loss", "dp_donor_gain", "dp_donor_loss",
        "max_delta_score", "gene_symbol",
        "source_dataset", "data_release", "annotation_source",
    }
    assert expected_keys.issubset(fields.keys())


def test_position_outside_any_gene_window_is_no_data_not_error():
    """
    A position that Illumina's model did not score must return
    status='no_data', not raise. Chromosome 1, position 1 is
    intergenic in GRCh38 and should not be in the masked SNV file.
    """
    result = annotate("1", 1, "A", "T")
    assert result["status"] == STATUS_NO_DATA


def test_cache_avoids_second_file_read(tmp_path, monkeypatch):
    """Repeated identical queries must hit the cache, not re-read the file."""
    import modules.spliceai.annotator as ann_mod
    from modules.spliceai.client import SpliceAILocalClient
    from modules.spliceai.tests.test_cache import CountingClient

    # Use a fresh tmp cache so a pre-existing on-disk cache entry can't
    # make both calls return before reaching CountingClient.fetch_variant_rows.
    real_cfg = _real_get_config()

    class _TmpCacheConfig:
        cache_dir = tmp_path / "cache"
        def version(self, key): return real_cfg.version(key)

    monkeypatch.setattr(ann_mod, "get_config", _TmpCacheConfig)

    rm = _real_get_reference_manager()
    resource = rm.get("spliceai")
    client = CountingClient(resource)

    annotate("1", 69090, "A", "T", client=client)
    annotate("1", 69090, "A", "T", client=client)
    assert client.fetch_count == 1


def test_source_version_matches_pinned_config_version():
    """
    The envelope's source_version must equal the pinned spliceai_version
    from config.yaml — this is the cache-key guarantee.
    """
    from shared.config import get_config
    cfg = get_config()
    expected_version = cfg.version("spliceai_version")

    result = annotate("1", 69090, "A", "T")
    assert result["source_version"] == expected_version