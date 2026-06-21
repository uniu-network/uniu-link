import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update, and_, BigInteger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.api_key import ApiKey
from app.services.redis_client import get_redis

logger = get_logger(__name__)

API_KEY_PREFIX = "sk-"
API_KEY_CACHE_PREFIX = "apikey:"
API_KEY_CACHE_TTL = 300
API_KEY_RATE_PREFIX = "apikey_rl:"

def generate_api_key() -> tuple[str, str, str]:
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[:8]
    return raw, key_hash, key_prefix

async def verify_api_key(api_key: str) -> Optional[dict]:
    if not api_key:
        return None

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    redis = await get_redis()
    cache_key = API_KEY_CACHE_PREFIX + key_hash
    cached = await redis.get(cache_key)
    if cached:
        info = json.loads(cached)

        if info.get("expires_at"):
            try:
                expires = datetime.fromisoformat(info["expires_at"])
                if expires < datetime.now(expires.tzinfo):
                    return None
            except (ValueError, TypeError):
                pass

        if not info.get("is_active", False):
            return None
        return info

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        api_key_obj = result.scalar_one_or_none()

    if not api_key_obj:
        return None

    if not api_key_obj.is_active:
        return None

    if api_key_obj.expires_at:
        if api_key_obj.expires_at < datetime.now(api_key_obj.expires_at.tzinfo):
            return None

    allowed_models = None
    if api_key_obj.allowed_models:
        try:
            parsed = json.loads(api_key_obj.allowed_models)
            if isinstance(parsed, list) and len(parsed) > 0:
                allowed_models = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    info = {
        "id": api_key_obj.id,
        "name": api_key_obj.name,
        "key_hash": api_key_obj.key_hash,
        "key_prefix": api_key_obj.key_prefix,
        "is_active": api_key_obj.is_active,
        "expires_at": api_key_obj.expires_at.isoformat() if api_key_obj.expires_at else None,
        "max_tokens": api_key_obj.max_tokens,
        "used_tokens": api_key_obj.used_tokens,
        "allowed_models": allowed_models,
        "rate_limit": api_key_obj.rate_limit,
    }

    await redis.set(cache_key, json.dumps(info), ex=API_KEY_CACHE_TTL)

    return info

def check_model_access(key_info: dict, model: str) -> bool:
    allowed = key_info.get("allowed_models")
    if not allowed:
        return True
    return model in allowed

async def check_key_rate_limit(key_info: dict) -> tuple[bool, str]:
    rate_limit = key_info.get("rate_limit")
    if not rate_limit or rate_limit <= 0:
        return True, ""

    redis = await get_redis()
    key_hash = key_info["key_hash"]
    rl_key = f"{API_KEY_RATE_PREFIX}{key_hash}"

    now = time.time()
    window_start = int(now) // 60 * 60
    window_key = f"{rl_key}:{window_start}"

    count = await redis.incr(window_key)
    if count == 1:
        await redis.expire(window_key, 120)

    if count > rate_limit:
        return False, f"API key rate limit exceeded ({rate_limit} req/min)"

    return True, ""

async def increment_token_usage(api_key_id: str, token_count: int) -> None:
    if not api_key_id or token_count <= 0:
        return

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == api_key_id)
            .values(used_tokens=ApiKey.used_tokens + token_count)
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ApiKey.key_hash).where(ApiKey.id == api_key_id)
        )
        key_hash = result.scalar_one_or_none()

    if key_hash:
        try:
            await invalidate_api_key_cache(key_hash)
        except Exception as e:
            logger.warning(
                "Failed to invalidate API key cache after token usage update",
                extra={"api_key_id": api_key_id, "error": str(e)[:200]},
            )

async def invalidate_api_key_cache(key_hash: str) -> None:
    redis = await get_redis()
    cache_key = API_KEY_CACHE_PREFIX + key_hash
    await redis.delete(cache_key)
