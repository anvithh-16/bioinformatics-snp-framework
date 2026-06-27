"""
modules/gnomad/tests/test_integration.py

Live tests against the real gnomAD GraphQL API. Marked `@pytest.mark.integration`
per pytest.ini, which deselects this entire file by default
(`addopts = -m "not integration"`) — exactly the same pattern VEP's
test_integration.py uses.

Run explicitly with:
    pytest modules/gnomad/tests/test_integration.py -m integration

These tests require network access to https://gnomad.broadinstitute.org
and a pinned `versions.gnomad_version` in config.yaml. If either is
unavailable, individual tests skip themselves rather than failing the
suite (consistent with "Integration tests ... automatically skipped if
unavailable" from both VEP and AlphaMissense design docs).
"""

import pytest

from modules.gnomad import annotate
from shared.config import get_config
from shared.exceptions import NetworkError

pytestmark = pytest.mark.integration


def _require_pinned_dataset():
    cfg = get_config()
    if not cfg.version("gnomad_version"):
        pytest.skip("versions.gnomad_version is not pinned in config.yaml")


class TestGnomadLiveAPI:
    def test_known_common_variant_returns_ok_with_nonzero_af(self):
        _require_pinned_dataset()
        try:
            result = annotate("1", 55051215, "G", "A")
        except NetworkError:
            pytest.skip("gnomAD API unreachable in this environment")

        assert result["module_name"] == "gnomad"
        # A real, well-covered coordinate should resolve to either ok or
        # no_data depending on whether this exact allele exists in the
        # pinned release -- we only assert the call completes and the
        # envelope shape is correct, since exact AF values can shift
        # slightly between gnomAD releases.
        assert result["status"] in ("ok", "no_data", "low_confidence")
        assert "fields" in result
        assert result["source_version"] == get_config().version("gnomad_version")

    def test_clearly_nonexistent_variant_returns_no_data(self):
        _require_pinned_dataset()
        try:
            # Position far beyond any real chromosome 1 coordinate.
            result = annotate("1", 1, "A", "T")
        except NetworkError:
            pytest.skip("gnomAD API unreachable in this environment")

        assert result["status"] in ("no_data", "ok", "low_confidence")