from __future__ import annotations

import time

from app.services.cache import TTLCache


class TestTTLCacheBasics:
    def test_set_and_get(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("k1", {"data": 42})
        assert cache.get("k1") == {"data": 42}

    def test_get_missing_key_returns_none(self):
        cache = TTLCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_size_reflects_entries(self):
        cache = TTLCache(ttl_seconds=60)
        assert cache.size == 0
        cache.set("a", 1)
        cache.set("b", 2)
        assert cache.size == 2

    def test_overwrite_existing_key(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", "old")
        cache.set("k", "new")
        assert cache.get("k") == "new"
        assert cache.size == 1


class TestTTLCacheExpiration:
    def test_expired_entry_returns_none(self):
        """Entry with very short TTL should expire after sleeping."""
        cache = TTLCache(ttl_seconds=3600)
        # Manually set an already-expired entry by backdating expires_at
        cache._store["k"] = ("value", time.time() - 1)
        assert cache.get("k") is None

    def test_expired_entry_is_cleaned_up(self):
        cache = TTLCache(ttl_seconds=60)
        cache._store["k"] = ("value", time.time() - 1)
        cache.get("k")  # triggers cleanup
        assert cache.size == 0

    def test_custom_ttl_per_entry(self):
        cache = TTLCache(ttl_seconds=60)
        # Short entry: already expired
        cache._store["short"] = ("val", time.time() - 1)
        # Long entry: set normally with long TTL
        cache.set("long", "val", ttl=3600)
        assert cache.get("short") is None
        assert cache.get("long") == "val"

    def test_ttl_zero_expires_immediately(self):
        """ttl=0 means expire immediately — entry should not be accessible."""
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", "value", ttl=0)
        # With explicit None check, ttl=0 means expires_at = time.time() + 0
        # which is immediately in the past (or at the exact boundary)
        # The entry should be expired on next get
        assert cache.get("k") is None

    def test_non_expired_entry_accessible(self):
        cache = TTLCache(ttl_seconds=3600)
        cache.set("k", "value")
        assert cache.get("k") == "value"

    def test_init_ttl_zero_uses_zero_not_default(self):
        """TTLCache(ttl_seconds=0) should use 0, not fall back to config default."""
        cache = TTLCache(ttl_seconds=0)
        assert cache._ttl == 0
        cache.set("k", "value")
        # TTL=0 → expires immediately
        assert cache.get("k") is None


class TestTTLCacheInvalidateAndClear:
    def test_invalidate_removes_key(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", "value")
        cache.invalidate("k")
        assert cache.get("k") is None
        assert cache.size == 0

    def test_invalidate_missing_key_no_error(self):
        cache = TTLCache(ttl_seconds=60)
        cache.invalidate("nonexistent")  # should not raise

    def test_clear_removes_all(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None


class TestTTLCacheValueTypes:
    def test_stores_none_value(self):
        """None is a valid value — distinct from 'not found'."""
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", None)
        # This is tricky: get returns None for both missing and stored-None.
        # But size confirms it's stored.
        assert cache.size == 1

    def test_stores_complex_nested_dict(self):
        cache = TTLCache(ttl_seconds=60)
        data = {
            "address": "0xabc",
            "signals": [{"id": "p1", "interacted": True}],
            "summary": {"score": 0.85},
        }
        cache.set("k", data)
        retrieved = cache.get("k")
        assert retrieved["address"] == "0xabc"
        assert len(retrieved["signals"]) == 1
        assert retrieved["summary"]["score"] == 0.85

    def test_stores_list_value(self):
        cache = TTLCache(ttl_seconds=60)
        cache.set("k", [1, 2, 3])
        assert cache.get("k") == [1, 2, 3]
