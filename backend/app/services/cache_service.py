import hashlib
import json
from typing import Any
from app.core.config import settings
from app.core.logging import get_logger
from app.services.redis_client import get_redis

logger = get_logger(__name__)

CACHE_PREFIX = "cache:response:"
CACHE_STATS_PREFIX = "cache:stats:"


def generate_cache_key(
    api_type: str,
    model: str,
    request_body: dict,
    api_key_hash: str,
    exclude_fields: list[str] | None = None,
) -> str:
    cache_body = dict(request_body)
    if exclude_fields:
        for field in exclude_fields:
            cache_body.pop(field, None)

    core_fields = {}
    for key in ("model", "messages", "input", "instructions", "system", "prompt",
                 "temperature", "top_p", "max_tokens", "max_output_tokens", "stop",
                 "presence_penalty", "frequency_penalty", "tools", "tool_choice",
                 "response_format", "text", "reasoning"):
        if key in cache_body:
            core_fields[key] = cache_body[key]

    key_str = f"{api_type}:{model}:{json.dumps(core_fields, sort_keys=True, ensure_ascii=False)}"
    key_hash = hashlib.sha256(key_str.encode()).hexdigest()

    return f"{CACHE_PREFIX}{api_key_hash}:{model}:{key_hash}"


async def get_cached_response(cache_key: str) -> dict | None:
    try:
        redis = await get_redis()
        data = await redis.get(cache_key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.error(f"Cache get error: {e}")
    return None


async def set_cached_response(
    cache_key: str,
    response_data: dict,
    ttl_seconds: int | None = None,
):
    try:
        redis = await get_redis()
        ttl = ttl_seconds or settings.cache_default_ttl
        await redis.setex(cache_key, ttl, json.dumps(response_data, ensure_ascii=False))
    except Exception as e:
        logger.error(f"Cache set error: {e}")


async def delete_cache_for_model(model: str):
    try:
        redis = await get_redis()
        pattern = f"{CACHE_PREFIX}*:{model}:*"
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        logger.info(f"Cleared {deleted} cache entries for model {model}")
    except Exception as e:
        logger.error(f"Cache clear error: {e}")


async def clear_all_cache():
    try:
        redis = await get_redis()
        pattern = f"{CACHE_PREFIX}*"
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=200)
            if keys:
                await redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        logger.info(f"Cleared all {deleted} cache entries")
    except Exception as e:
        logger.error(f"Cache clear all error: {e}")


async def record_cache_hit(model: str):
    redis = await get_redis()
    key = f"{CACHE_STATS_PREFIX}hit:{model}"
    await redis.incr(key)


async def record_cache_miss(model: str):
    redis = await get_redis()
    key = f"{CACHE_STATS_PREFIX}miss:{model}"
    await redis.incr(key)


async def get_cache_stats(model: str | None = None) -> dict:
    redis = await get_redis()
    if model:
        hit = int(await redis.get(f"{CACHE_STATS_PREFIX}hit:{model}") or 0)
        miss = int(await redis.get(f"{CACHE_STATS_PREFIX}miss:{model}") or 0)
        total = hit + miss
        hit_rate = round(hit / total * 100, 2) if total > 0 else 0
        return {"model": model, "hit": hit, "miss": miss, "total": total, "hit_rate": hit_rate}

    all_stats = []
    cursor = 0
    models_set: set[str] = set()
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{CACHE_STATS_PREFIX}hit:*", count=100)
        for key in keys:
            models_set.add(key.replace(f"{CACHE_STATS_PREFIX}hit:", ""))
        if cursor == 0:
            break

    for m in models_set:
        hit = int(await redis.get(f"{CACHE_STATS_PREFIX}hit:{m}") or 0)
        miss = int(await redis.get(f"{CACHE_STATS_PREFIX}miss:{m}") or 0)
        total = hit + miss
        hit_rate = round(hit / total * 100, 2) if total > 0 else 0
        all_stats.append({"model": m, "hit": hit, "miss": miss, "total": total, "hit_rate": hit_rate})

    return {"models": all_stats}
