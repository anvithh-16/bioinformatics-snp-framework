from __future__ import annotations

from shared.reference import get_reference_manager

from modules.alphamissense.annotator import annotate
from modules.alphamissense.client import AlphaMissenseClient
from modules.alphamissense.constants import STATUS_NO_DATA, STATUS_OK


class CountingClient(AlphaMissenseClient):
    """Spy that counts how many times the underlying file is actually read."""

    def __init__(self, resource):
        super().__init__(resource=resource)
        self.fetch_count = 0

    def fetch_raw_rows(self, chrom, position):
        self.fetch_count += 1
        return super().fetch_raw_rows(chrom, position)


def _client(registered_resource):
    resource = get_reference_manager().get("alphamissense")
    return CountingClient(resource)


def test_cache_hit_avoids_second_file_read(registered_resource):
    client = _client(registered_resource)

    first = annotate("17", 7674220, "C", "T", client=client)
    second = annotate("17", 7674220, "C", "T", client=client)

    assert first == second
    assert first["status"] == STATUS_OK
    assert client.fetch_count == 1


def test_no_data_results_are_also_cached(registered_resource):
    """
    A clean zero-match outcome against a static local file is
    deterministic, not a transient failure -- caching it is correct
    and is the documented design decision (Conversation 4A, section 24),
    unlike VEP's API-backed caching where an empty response should not
    be assumed safe to cache.
    """
    client = _client(registered_resource)

    first = annotate("1", 999999999, "A", "T", client=client)
    second = annotate("1", 999999999, "A", "T", client=client)

    assert first["status"] == STATUS_NO_DATA
    assert second["status"] == STATUS_NO_DATA
    assert client.fetch_count == 1


def test_different_variants_are_cached_independently(registered_resource):
    client = _client(registered_resource)

    pathogenic = annotate("17", 7674220, "C", "T", client=client)
    benign = annotate("19", 44908684, "T", "C", client=client)

    assert pathogenic["fields"]["am_class"] == "likely_pathogenic"
    assert benign["fields"]["am_class"] == "likely_benign"
    assert client.fetch_count == 2  # both were genuine, distinct lookups


def test_cache_key_is_scoped_by_resource_version(tmp_path, monkeypatch):
    """
    If the pinned AlphaMissense version changes, previously cached
    results for the old version must not leak into the new version's
    results -- the cache key includes data_release specifically so a
    version bump invalidates everything without a time-based TTL.
    """
    from modules.alphamissense.tests.conftest import write_fixture_file
    from shared.reference import _set_resource_for_tests

    rows_v1 = [("chr1", "555", "A", "T", "hg38", "P1", "ENST1", "X1Y", "0.9", "likely_pathogenic")]
    rows_v2 = [("chr1", "555", "A", "T", "hg38", "P1", "ENST1", "X1Y", "0.1", "likely_benign")]

    file_v1 = write_fixture_file(tmp_path / "v1.tsv", rows_v1)
    file_v2 = write_fixture_file(tmp_path / "v2.tsv", rows_v2)

    _set_resource_for_tests("alphamissense", file_v1, "zenodo:v1")
    result_v1 = annotate("1", 555, "A", "T")
    assert result_v1["fields"]["am_class"] == "likely_pathogenic"
    assert result_v1["source_version"] == "zenodo:v1"

    _set_resource_for_tests("alphamissense", file_v2, "zenodo:v2")
    result_v2 = annotate("1", 555, "A", "T")
    assert result_v2["fields"]["am_class"] == "likely_benign"
    assert result_v2["source_version"] == "zenodo:v2"