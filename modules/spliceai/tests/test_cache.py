from __future__ import annotations

"""
Cache behaviour tests. Verifies hit/miss/never-cache-errors behaviour
and version-scoped key isolation using tmp_path-isolated DiskCache
instances (no cross-test SQLite pollution).
"""

import pytest

from modules.spliceai.annotator import annotate
from modules.spliceai.client import SpliceAILocalClient
from modules.spliceai.constants import STATUS_NO_DATA, STATUS_OK
from modules.spliceai.tests.conftest import RESOURCE_VERSION, write_fixture_vcf


class CountingClient(SpliceAILocalClient):
    """Spy that counts how many times the underlying file is actually read."""

    def __init__(self, resource):
        super().__init__(resource=resource)
        self.fetch_count = 0

    def fetch_variant_rows(self, chrom, position):
        self.fetch_count += 1
        return super().fetch_variant_rows(chrom, position)


def test_cache_hit_avoids_second_file_read(registered_resource):
    client = CountingClient(registered_resource)

    first = annotate("17", 41276045, "G", "T", client=client)
    second = annotate("17", 41276045, "G", "T", client=client)

    assert first == second
    assert first["status"] == STATUS_OK
    assert client.fetch_count == 1


def test_no_data_results_are_cached(registered_resource):
    """
    A confirmed absence against a static pinned file is a stable,
    reproducible fact — it must be cached, matching the design decision
    in Section 15 and the AlphaMissense/gnomAD precedent.
    """
    client = CountingClient(registered_resource)

    first = annotate("1", 999999999, "A", "T", client=client)
    second = annotate("1", 999999999, "A", "T", client=client)

    assert first["status"] == STATUS_NO_DATA
    assert second["status"] == STATUS_NO_DATA
    assert client.fetch_count == 1


def test_different_variants_are_cached_independently(registered_resource):
    client = CountingClient(registered_resource)

    brca1 = annotate("17", 41276045, "G", "T", client=client)
    intronic = annotate("2", 179415121, "G", "C", client=client)

    assert brca1["status"] == STATUS_OK
    assert intronic["status"] == STATUS_OK
    assert client.fetch_count == 2


def test_cache_key_scoped_by_resource_version(tmp_path, fake_reference_manager, monkeypatch):
    """
    A version bump must invalidate previously cached results: the cache key
    includes the pinned version string, so different version strings produce
    different keys and therefore different cache entries.
    """
    import modules.spliceai.annotator as ann_mod
    from pathlib import Path

    class VersionedConfig:
        def __init__(self, version, cache_dir):
            self._version = version
            self.cache_dir = cache_dir

        def version(self, key):
            return self._version if key == "spliceai_version" else None

    rows_v1 = [("chr1", "555", ".", "A", "T", ".", ".", "SpliceAI=T|GENE|0.9|0.1|0.1|0.1|1|2|3|4")]
    rows_v2 = [("chr1", "555", ".", "A", "T", ".", ".", "SpliceAI=T|GENE|0.1|0.0|0.0|0.0|1|2|3|4")]

    file_v1 = write_fixture_vcf(tmp_path / "v1.vcf", rows_v1)
    file_v2 = write_fixture_vcf(tmp_path / "v2.vcf", rows_v2)

    cache_dir = tmp_path / "cache"

    fake_reference_manager.set_resource(file_v1, "spliceai:v1")
    monkeypatch.setattr(ann_mod, "get_config", lambda: VersionedConfig("spliceai:v1", cache_dir))
    result_v1 = annotate("1", 555, "A", "T")
    assert result_v1["fields"]["ds_acceptor_gain"] == pytest.approx(0.9)
    assert result_v1["source_version"] == "spliceai:v1"

    fake_reference_manager.set_resource(file_v2, "spliceai:v2")
    monkeypatch.setattr(ann_mod, "get_config", lambda: VersionedConfig("spliceai:v2", cache_dir))
    result_v2 = annotate("1", 555, "A", "T")
    assert result_v2["fields"]["ds_acceptor_gain"] == pytest.approx(0.1)
    assert result_v2["source_version"] == "spliceai:v2"