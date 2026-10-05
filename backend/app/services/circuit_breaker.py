import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import anyio

from app.core.config import settings
from app.core.logging import get_logger
from app.services.redis_client import get_redis

logger = get_logger(__name__)

CB_STATE_KEY = "circuit_breaker:{}:state"
CB_FAIL_COUNT_KEY = "circuit_breaker:{}:fail_count"
CB_LAST_FAIL_KEY = "circuit_breaker:{}:last_fail"
CB_HALF_OPEN_COUNT_KEY = "circuit_breaker:{}:half_open_count"
CB_PROBES_KEY = "circuit_breaker:{}:probes"
CB_GENERATION_KEY = "circuit_breaker:{}:generation"


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitPermit:
    channel_id: str
    token: str
    generation: int
    half_open: bool
    lease_seconds: int


def _keys(channel_id: str) -> list[str]:
    return [key.format(channel_id) for key in (
        CB_STATE_KEY, CB_FAIL_COUNT_KEY, CB_LAST_FAIL_KEY,
        CB_PROBES_KEY, CB_GENERATION_KEY, CB_HALF_OPEN_COUNT_KEY,
    )]


# Generation checks prevent an old in-flight success from closing a circuit
# that was subsequently opened. Probe leases recover after worker crashes.
_ACQUIRE = """
local state = redis.call('GET', KEYS[1]) or 'closed'
local generation = tonumber(redis.call('GET', KEYS[5]) or '0')
local now = tonumber(ARGV[1])
if state == 'open' then
    local failed = tonumber(redis.call('GET', KEYS[3]) or '0')
    if now - failed < tonumber(ARGV[2]) then return {0, generation, 0} end
    redis.call('SET', KEYS[1], 'half_open')
    generation = redis.call('INCR', KEYS[5])
    redis.call('DEL', KEYS[4], KEYS[6])
    state = 'half_open'
end
if state == 'half_open' then
    redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', now)
    if redis.call('ZCARD', KEYS[4]) >= tonumber(ARGV[3]) then
        return {0, generation, 1}
    end
    redis.call('ZADD', KEYS[4], now + tonumber(ARGV[5]), ARGV[4])
    redis.call('EXPIRE', KEYS[4], tonumber(ARGV[5]) * 2)
    return {1, generation, 1}
end
return {1, generation, 0}
"""

_SETTLE = """
local generation = tonumber(redis.call('GET', KEYS[5]) or '0')
if generation ~= tonumber(ARGV[1]) then return 0 end
local state = redis.call('GET', KEYS[1]) or 'closed'
if state == 'half_open' then
    local expires = redis.call('ZSCORE', KEYS[4], ARGV[2])
    if not expires or tonumber(expires) <= tonumber(ARGV[4]) then return 0 end
end
redis.call('ZREM', KEYS[4], ARGV[2])
if ARGV[3] == 'success' then
    if state == 'open' then return 0 end
    if state == 'half_open' then redis.call('INCR', KEYS[5]) end
    redis.call('SET', KEYS[1], 'closed')
    redis.call('DEL', KEYS[2], KEYS[3], KEYS[4], KEYS[6])
    return 0
end
if state == 'open' then return 1 end
local count = redis.call('INCR', KEYS[2])
if count == 1 then redis.call('EXPIRE', KEYS[2], tonumber(ARGV[6])) end
redis.call('SET', KEYS[3], ARGV[4])
if state == 'half_open' or count >= tonumber(ARGV[5]) then
    redis.call('SET', KEYS[1], 'open')
    redis.call('INCR', KEYS[5])
    redis.call('DEL', KEYS[2], KEYS[4], KEYS[6])
    return 1
end
return 0
"""

_RENEW = """
if tonumber(redis.call('GET', KEYS[5]) or '0') ~= tonumber(ARGV[1]) then return 0 end
local expires = redis.call('ZSCORE', KEYS[4], ARGV[2])
if expires and tonumber(expires) > tonumber(ARGV[3]) then
    redis.call('ZADD', KEYS[4], tonumber(ARGV[3]) + tonumber(ARGV[4]), ARGV[2])
    redis.call('EXPIRE', KEYS[4], tonumber(ARGV[4]) * 2)
    return 1
end
return 0
"""


async def get_circuit_state(channel_id: str) -> str:
    redis = await get_redis()
    return await redis.get(CB_STATE_KEY.format(channel_id)) or CircuitState.CLOSED


async def should_allow_request(channel_id: str) -> bool:
    """Read-only candidate filtering. Only acquire_request consumes a slot."""
    redis = await get_redis()
    state = await get_circuit_state(channel_id)
    if state == CircuitState.OPEN:
        failed = await redis.get(CB_LAST_FAIL_KEY.format(channel_id))
        return not failed or time.time() - float(failed) >= settings.circuit_breaker_cooldown_seconds
    if state == CircuitState.HALF_OPEN:
        count = await redis.zcount(CB_PROBES_KEY.format(channel_id), f"({time.time()}", "+inf")
        return count < max(1, settings.circuit_breaker_half_open_max_requests)
    return True


async def acquire_request(channel_id: str, timeout: int = 30) -> CircuitPermit | None:
    redis = await get_redis()
    token = uuid.uuid4().hex
    lease_seconds = max(int(timeout * 2), 60)
    result = await cast(Any, redis).eval(
        _ACQUIRE, 6, *_keys(channel_id), time.time(), settings.circuit_breaker_cooldown_seconds,
        max(1, settings.circuit_breaker_half_open_max_requests), token, lease_seconds,
    )
    if not result[0]:
        return None
    return CircuitPermit(channel_id, token, int(result[1]), bool(result[2]), lease_seconds)


async def _renew_permit(permit: CircuitPermit) -> None:
    while True:
        await asyncio.sleep(permit.lease_seconds / 3)
        redis = await get_redis()
        renewed = await cast(Any, redis).eval(
            _RENEW, 6, *_keys(permit.channel_id), permit.generation, permit.token,
            time.time(), permit.lease_seconds,
        )
        if not renewed:
            return


@asynccontextmanager
async def request_permit(channel_id: str, timeout: int = 30):
    permit = await acquire_request(channel_id, timeout)
    heartbeat = asyncio.create_task(_renew_permit(permit)) if permit and permit.half_open else None
    try:
        yield permit
    finally:
        with anyio.CancelScope(shield=True):
            if heartbeat:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Failed to renew circuit probe lease")
            if permit and permit.half_open:
                try:
                    redis = await get_redis()
                    await redis.zrem(CB_PROBES_KEY.format(channel_id), permit.token)
                except Exception:
                    # The lease expires if Redis is unavailable. Cleanup must
                    # not turn a completed upstream call into a retry.
                    logger.exception("Failed to release circuit probe lease")


async def _settle(channel_id: str, outcome: str, permit: CircuitPermit | None) -> bool:
    redis = await get_redis()
    generation = permit.generation if permit else int(await redis.get(CB_GENERATION_KEY.format(channel_id)) or 0)
    return bool(await cast(Any, redis).eval(
        _SETTLE, 6, *_keys(channel_id), generation, permit.token if permit else "", outcome,
        time.time(), max(1, settings.circuit_breaker_failure_threshold),
        max(settings.circuit_breaker_cooldown_seconds, 30),
    ))


async def record_success(channel_id: str, permit: CircuitPermit | None = None):
    await _settle(channel_id, "success", permit)


async def record_failure(channel_id: str, permit: CircuitPermit | None = None) -> bool:
    return await _settle(channel_id, "failure", permit)


async def is_circuit_open(channel_id: str) -> bool:
    return await get_circuit_state(channel_id) == CircuitState.OPEN


async def reset_circuit(channel_id: str):
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.incr(CB_GENERATION_KEY.format(channel_id))
    pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.CLOSED)
    pipe.delete(*[key for key in _keys(channel_id) if key not in (
        CB_STATE_KEY.format(channel_id), CB_GENERATION_KEY.format(channel_id),
    )])
    await pipe.execute()


async def get_circuit_info(channel_id: str) -> dict:
    redis = await get_redis()
    state = await get_circuit_state(channel_id)
    fail_count = await redis.get(CB_FAIL_COUNT_KEY.format(channel_id))
    last_fail = await redis.get(CB_LAST_FAIL_KEY.format(channel_id))
    count = await redis.zcount(CB_PROBES_KEY.format(channel_id), f"({time.time()}", "+inf")
    return {"circuit_state": state, "fail_count": int(fail_count or 0),
            "last_fail_ts": float(last_fail) if last_fail else None, "half_open_count": count}
