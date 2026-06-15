import time
import asyncio
from typing import Any, cast

from app.core.config import settings
from app.services.redis_client import get_redis
from app.core.logging import get_logger

logger = get_logger(__name__)

RL_GLOBAL_KEY = "rate_limit:global"
RL_KEY_PREFIX = "rate_limit:key:"
RL_MODEL_PREFIX = "rate_limit:model:"


async def check_rate_limit(
    api_key_hash: str,
    model: str,
) -> tuple[bool, str]:
    redis = await get_redis()
    now = time.time()
    window = 1.0

    lua_script = """
    local global_key = KEYS[1]
    local key_prefix = KEYS[2]
    local model_prefix = KEYS[3]
    local api_key_hash = ARGV[1]
    local model = ARGV[2]
    local global_rps = tonumber(ARGV[3])
    local key_rps = tonumber(ARGV[4])
    local model_rps = tonumber(ARGV[5])

    local global_ts_key = global_key .. ":ts"
    local global_count = redis.call('INCR', global_ts_key)
    redis.call('EXPIRE', global_ts_key, 1)
    if global_count > global_rps then
        return {0, 'global_rate_limit_exceeded'}
    end

    local key_count = redis.call('INCR', key_prefix .. api_key_hash .. ":ts")
    redis.call('EXPIRE', key_prefix .. api_key_hash .. ":ts", 1)
    if key_count > key_rps then
        return {0, 'key_rate_limit_exceeded'}
    end

    local model_count = redis.call('INCR', model_prefix .. model .. ":ts")
    redis.call('EXPIRE', model_prefix .. model .. ":ts", 1)
    if model_count > model_rps then
        return {0, 'model_rate_limit_exceeded'}
    end

    return {1, ''}
    """

    result = cast(list[Any], await cast(Any, redis).eval(
        lua_script,
        3,
        RL_GLOBAL_KEY,
        RL_KEY_PREFIX,
        RL_MODEL_PREFIX,
        api_key_hash,
        model,
        str(settings.rate_limit_global_rps),
        str(settings.rate_limit_per_key_rps),
        str(settings.rate_limit_per_model_rps),
    ))

    allowed = bool(result[0])
    reason = str(result[1]) if len(result) > 1 else ""

    if not allowed:
        logger.warning(
            f"Rate limit exceeded: {reason}",
            extra={"api_key_hash": api_key_hash[:8], "model": model, "trace_id": "rate_limit"},
        )

    return allowed, reason
