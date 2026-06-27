import time
from pathlib import Path

from shared.cache import MemoryCache, DiskCache, make_key


def test_memory_cache_set_get():
    cache = MemoryCache()
    key = make_key("service", "1:100:A:G")
    assert cache.get(key) is None
    cache.set(key, {"score": 0.9})
    assert cache.get(key) == {"score": 0.9}
    assert cache.stats.hits == 1
    assert cache.stats.misses == 1


def test_memory_cache_ttl_expiry():
    cache = MemoryCache()
    key = "k"
    cache.set(key, "value", ttl_seconds=0.05)
    assert cache.get(key) == "value"
    time.sleep(0.1)
    assert cache.get(key) is None


def test_disk_cache_persists(tmp_path: Path):
    db_path = tmp_path / "test_cache.sqlite"
    cache = DiskCache(db_path)
    key = make_key("vep", "1:100:A:G")
    cache.set(key, {"consequence": "missense_variant"})

    # Re-open as a fresh instance to confirm persistence.
    reopened = DiskCache(db_path)
    assert reopened.get(key) == {"consequence": "missense_variant"}


def test_disk_cache_ttl_expiry(tmp_path: Path):
    cache = DiskCache(tmp_path / "ttl_cache.sqlite")
    key = "k"
    cache.set(key, "value", ttl_seconds=0.05)
    time.sleep(0.1)
    assert cache.get(key) is None


def test_disk_cache_invalidate(tmp_path: Path):
    cache = DiskCache(tmp_path / "inv_cache.sqlite")
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None
