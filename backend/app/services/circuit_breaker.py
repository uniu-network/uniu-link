import time
from app.core.config import settings
from app.services.redis_client import get_redis
from app.core.logging import get_logger

logger = get_logger(__name__)

CB_STATE_KEY = "circuit_breaker:{}:state"
CB_FAIL_COUNT_KEY = "circuit_breaker:{}:fail_count"
CB_LAST_FAIL_KEY = "circuit_breaker:{}:last_fail"
CB_HALF_OPEN_COUNT_KEY = "circuit_breaker:{}:half_open_count"


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def _state_ttl() -> int:
    return max(settings.circuit_breaker_cooldown_seconds * 4, 60)


def _fail_count_ttl() -> int:
    return max(settings.circuit_breaker_cooldown_seconds, 30)


def _last_fail_ttl() -> int:
    return max(settings.circuit_breaker_cooldown_seconds * 2, 60)


def _half_open_count_ttl() -> int:
    return max(settings.circuit_breaker_cooldown_seconds * 2, 60)


async def get_circuit_state(channel_id: str) -> str:
    redis = await get_redis()
    state = await redis.get(CB_STATE_KEY.format(channel_id))
    return state or CircuitState.CLOSED


async def record_success(channel_id: str):
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.CLOSED, ex=_state_ttl())
    pipe.delete(CB_FAIL_COUNT_KEY.format(channel_id))
    pipe.delete(CB_LAST_FAIL_KEY.format(channel_id))
    pipe.delete(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
    await pipe.execute()


async def record_failure(channel_id: str) -> bool:
    redis = await get_redis()
    now = time.time()
    state = await get_circuit_state(channel_id)

    if state == CircuitState.HALF_OPEN:
        pipe = redis.pipeline()
        pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.OPEN, ex=_state_ttl())
        pipe.set(CB_LAST_FAIL_KEY.format(channel_id), now, ex=_last_fail_ttl())
        pipe.delete(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
        pipe.delete(CB_FAIL_COUNT_KEY.format(channel_id))
        await pipe.execute()
        logger.warning(f"Circuit re-opened for channel {channel_id} after half-open probe failure")
        return True

    if state == CircuitState.OPEN:
        return True

    fail_count_key = CB_FAIL_COUNT_KEY.format(channel_id)
    fail_count = await redis.incr(fail_count_key)
    if fail_count == 1:
        await redis.expire(fail_count_key, _fail_count_ttl())

    await redis.set(CB_LAST_FAIL_KEY.format(channel_id), now, ex=_last_fail_ttl())

    if fail_count >= settings.circuit_breaker_failure_threshold:
        pipe = redis.pipeline()
        pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.OPEN, ex=_state_ttl())
        pipe.delete(CB_FAIL_COUNT_KEY.format(channel_id))
        await pipe.execute()
        logger.warning(f"Circuit opened for channel {channel_id} after {fail_count} failures")
        return True

    return False


async def should_allow_request(channel_id: str) -> bool:
    redis = await get_redis()
    state = await get_circuit_state(channel_id)

    if state == CircuitState.OPEN:
        last_fail = await redis.get(CB_LAST_FAIL_KEY.format(channel_id))
        if last_fail:
            elapsed = time.time() - float(last_fail)
            if elapsed >= settings.circuit_breaker_cooldown_seconds:
                pipe = redis.pipeline()
                pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.HALF_OPEN, ex=_state_ttl())
                pipe.set(CB_HALF_OPEN_COUNT_KEY.format(channel_id), 0, ex=_half_open_count_ttl())
                await pipe.execute()
                state = CircuitState.HALF_OPEN
            else:
                return False
        else:
            pipe = redis.pipeline()
            pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.CLOSED, ex=_state_ttl())
            pipe.delete(CB_FAIL_COUNT_KEY.format(channel_id))
            pipe.delete(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
            await pipe.execute()
            return True

    if state == CircuitState.HALF_OPEN:
        count = await redis.incr(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
        if count > settings.circuit_breaker_half_open_max_requests:
            return False

    return True


async def is_circuit_open(channel_id: str) -> bool:
    state = await get_circuit_state(channel_id)
    return state == CircuitState.OPEN


async def reset_circuit(channel_id: str):
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.CLOSED, ex=_state_ttl())
    pipe.delete(CB_FAIL_COUNT_KEY.format(channel_id))
    pipe.delete(CB_LAST_FAIL_KEY.format(channel_id))
    pipe.delete(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
    await pipe.execute()


async def get_circuit_info(channel_id: str) -> dict:
    redis = await get_redis()
    state = await get_circuit_state(channel_id)
    fail_count = await redis.get(CB_FAIL_COUNT_KEY.format(channel_id))
    last_fail = await redis.get(CB_LAST_FAIL_KEY.format(channel_id))
    half_open_count = await redis.get(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
    return {
        "circuit_state": state,
        "fail_count": int(fail_count) if fail_count else 0,
        "last_fail_ts": float(last_fail) if last_fail else None,
        "half_open_count": int(half_open_count) if half_open_count else 0,
    }
