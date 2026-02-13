from __future__ import annotations

import time
from typing import Any

from app.config import settings


class TTLCache:
    def __init__(self, ttl_seconds: int | None = None):
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.cache_ttl_seconds

    def get(self, key: str) -> Any | None:
        if key in self._store:
            value, expires_at = self._store[key]
            if time.time() < expires_at:
                return value
            del self._store[key]
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = time.time() + (ttl if ttl is not None else self._ttl)
        self._store[key] = (value, expires_at)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


scan_cache = TTLCache()
