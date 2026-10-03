import asyncio
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.http_debug import log_upstream_request, log_upstream_response
from app.core.logging import get_logger
from app.core.encryption import key_encryption
from app.models.channel import Channel
from app.adapters.generic_adapter import get_adapter
from app.adapters.base_adapter import merge_custom_headers
from app.services.channel_probe import build_models_url, build_prompt_request
from app.services.request_transformer import normalize_channel_api_type
from app.services.redis_client import get_redis

logger = get_logger(__name__)

HEALTH_CHECK_KEY = "health_check:channel:{}"
DEFAULT_HEALTH_CHECK_PROMPT = "Hi, please respond with a short greeting to confirm you are working."


def _build_health_check_request(channel: Channel, api_type: str) -> dict | None:
    upstream_models = channel.upstream_models or []
    model = channel.health_check_model or (upstream_models[0] if upstream_models else "")
    if model and model not in upstream_models:
        return None
    if not model:
        return None

    return build_prompt_request(
        api_type,
        model,
        channel.health_check_prompt or DEFAULT_HEALTH_CHECK_PROMPT,
        channel.health_check_max_tokens or 32,
    )


async def _run_prompt_probe(
    client: httpx.AsyncClient,
    channel: Channel,
    api_type: str,
    headers: dict,
) -> httpx.Response | None:
    request_body = _build_health_check_request(channel, api_type)
    if request_body is None:
        return None

    adapter = get_adapter(channel.provider)
    provider_request = adapter.convert_request(request_body, api_type)
    url = adapter.get_url(channel.base_url, api_type)
    log_upstream_request(
        logger,
        "POST",
        url,
        provider_request,
        trace_id="health_check",
        channel=channel.name,
    )
    response = await client.post(url, json=provider_request, headers=headers)
    log_upstream_response(
        logger,
        "POST",
        url,
        response.status_code,
        response.text[:500],
        "health_check",
        channel.name,
    )
    return response


async def check_channel_health(channel: Channel) -> bool:
    try:
        api_key = key_encryption.decrypt(channel.encrypted_api_key)
        adapter = get_adapter(channel.provider)
        headers = adapter.get_headers(api_key) if api_key else {}
        headers = merge_custom_headers(headers, channel.custom_headers)
        api_type = normalize_channel_api_type(channel.api_type, channel.provider)

        async with httpx.AsyncClient(timeout=channel.timeout or 30) as client:
            if channel.health_check_mode == "prompt":
                resp = await _run_prompt_probe(client, channel, api_type, headers)
                if resp is None:
                    return False
            else:
                url = build_models_url(channel.base_url)
                log_upstream_request(logger, "GET", url, trace_id="health_check", channel=channel.name)
                resp = await client.get(url, headers=headers)
                log_upstream_response(logger, "GET", url, resp.status_code, resp.text, "health_check", channel.name)

                if not 200 <= resp.status_code < 300:
                    logger.info(
                        "Model list probe failed, falling back to prompt probe",
                        extra={
                            "channel": channel.name,
                            "status": resp.status_code,
                            "trace_id": "health_check",
                        },
                    )
                    prompt_response = await _run_prompt_probe(
                        client, channel, api_type, headers
                    )
                    if prompt_response is not None:
                        resp = prompt_response

            is_healthy = 200 <= resp.status_code < 300

        logger.info(
            "Health check result",
            extra={
                "channel": channel.name,
                "provider": channel.provider,
                "mode": channel.health_check_mode,
                "status": resp.status_code,
                "healthy": is_healthy,
                "trace_id": "health_check",
            },
        )
        return is_healthy
    except Exception as e:
        logger.warning(
            "Health check failed",
            extra={
                "channel": channel.name,
                "error": str(e),
                "trace_id": "health_check",
            },
        )
        return False


async def run_health_checks():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Channel))
        channels = result.scalars().all()

    redis = await get_redis()

    for channel in channels:
        is_healthy = await check_channel_health(channel)
        status = "healthy" if is_healthy else "unhealthy"
        await set_channel_health_status(channel.id, status, redis=redis)


async def set_channel_health_status(
    channel_id: str,
    status: str,
    *,
    redis=None,
) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Channel).where(Channel.id == channel_id))
        channel = result.scalar_one_or_none()
        if channel:
            channel.health_status = status
            session.add(channel)
            await session.commit()

    redis_client = redis if redis is not None else await get_redis()
    await redis_client.set(
        HEALTH_CHECK_KEY.format(channel_id),
        status,
        ex=settings.health_check_interval * 3,
    )


async def health_check_loop():
    while True:
        try:
            await run_health_checks()
        except Exception as e:
            logger.error(f"Health check loop error: {e}")
        await asyncio.sleep(settings.health_check_interval)


async def get_channel_health_status(channel_id: str) -> str:
    redis = await get_redis()
    status = await redis.get(HEALTH_CHECK_KEY.format(channel_id))
    if status:
        return status

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Channel).where(Channel.id == channel_id))
        ch = result.scalar_one_or_none()
        if ch:
            await redis.set(
                HEALTH_CHECK_KEY.format(channel_id),
                ch.health_status,
                ex=settings.health_check_interval * 3,
            )
            return ch.health_status
    return "unknown"
