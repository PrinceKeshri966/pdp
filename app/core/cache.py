"""
Optional Redis cache with in-memory fallback for dev.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MEMORY: dict[str, tuple[float, str]] = {}
_redis_client = None

TTL_SCRAPE = 6 * 3600
TTL_PREPROCESSOR = 12 * 3600
TTL_CONTENT = 24 * 3600
TTL_COMPETITORS = 12 * 3600


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]


def cache_key(prefix: str, url: str, extra: str = "") -> str:
    base = f"{prefix}:{_url_hash(url)}"
    return f"{base}:{extra}" if extra else base


async def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    redis_url = getattr(get_settings(), "redis_url", None) or ""
    if not redis_url:
        return None
    try:
        import redis.asyncio as redis

        _redis_client = redis.from_url(redis_url, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception as exc:
        logger.warning("cache.redis_unavailable", error=str(exc))
        return None


async def cache_get(key: str) -> Any | None:
    r = await _get_redis()
    if r:
        try:
            raw = await r.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    entry = _MEMORY.get(key)
    if entry and entry[0] > time.time():
        return json.loads(entry[1])
    return None


async def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    payload = json.dumps(value, default=str)
    r = await _get_redis()
    if r:
        try:
            await r.setex(key, ttl_seconds, payload)
            return
        except Exception:
            pass
    _MEMORY[key] = (time.time() + ttl_seconds, payload)


async def cached_scrape(url: str, fetcher) -> Any:
    key = cache_key("scrape", url)
    hit = await cache_get(key)
    if hit is not None:
        hit["_cache_hit"] = True
        return hit
    result = await fetcher()
    if result:
        await cache_set(key, result, TTL_SCRAPE)
    return result
