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


async def get_circuit_state(channel_id: str) -> str:
    redis = await get_redis()
    state = await redis.get(CB_STATE_KEY.format(channel_id))
    return state or CircuitState.CLOSED


async def record_success(channel_id: str):
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.CLOSED)
    pipe.delete(CB_FAIL_COUNT_KEY.format(channel_id))
    pipe.delete(CB_LAST_FAIL_KEY.format(channel_id))
    pipe.delete(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
    await pipe.execute()


async def record_failure(channel_id: str) -> bool:
    redis = await get_redis()
    now = time.time()

    state = await get_circuit_state(channel_id)

    if state == CircuitState.OPEN:
        last_fail = await redis.get(CB_LAST_FAIL_KEY.format(channel_id))
        if last_fail:
            elapsed = now - float(last_fail)
            if elapsed >= settings.circuit_breaker_cooldown_seconds:
                await redis.set(CB_STATE_KEY.format(channel_id), CircuitState.HALF_OPEN)
                await redis.set(CB_HALF_OPEN_COUNT_KEY.format(channel_id), 0)
                return False
        return True

    if state == CircuitState.HALF_OPEN:
        await redis.set(CB_STATE_KEY.format(channel_id), CircuitState.OPEN)
        await redis.set(CB_LAST_FAIL_KEY.format(channel_id), now)
        return True

    fail_count = await redis.incr(CB_FAIL_COUNT_KEY.format(channel_id))
    await redis.set(CB_LAST_FAIL_KEY.format(channel_id), now)

    if fail_count >= settings.circuit_breaker_failure_threshold:
        await redis.set(CB_STATE_KEY.format(channel_id), CircuitState.OPEN)
        logger.warning(f"Circuit opened for channel {channel_id} after {fail_count} failures")
        return True

    return False


async def is_circuit_open(channel_id: str) -> bool:
    state = await get_circuit_state(channel_id)
    return state == CircuitState.OPEN


async def should_allow_request(channel_id: str) -> bool:
    redis = await get_redis()
    state = await get_circuit_state(channel_id)

    if state == CircuitState.OPEN:
        return False

    if state == CircuitState.HALF_OPEN:
        count = await redis.incr(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
        if count > settings.circuit_breaker_half_open_max_requests:
            return False

    return True


async def reset_circuit(channel_id: str):
    redis = await get_redis()
    pipe = redis.pipeline()
    pipe.set(CB_STATE_KEY.format(channel_id), CircuitState.CLOSED)
    pipe.delete(CB_FAIL_COUNT_KEY.format(channel_id))
    pipe.delete(CB_LAST_FAIL_KEY.format(channel_id))
    pipe.delete(CB_HALF_OPEN_COUNT_KEY.format(channel_id))
    await pipe.execute()
