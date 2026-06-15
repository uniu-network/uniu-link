import random
import json
import time
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.config import settings
from app.models.model_config import ModelConfig
from app.models.model_channel_ref import ModelChannelRef
from app.models.channel import Channel
from app.services.health_checker import get_channel_health_status
from app.services.circuit_breaker import is_circuit_open, should_allow_request

logger = get_logger(__name__)


class ChannelInfo:

    def __init__(
        self,
        ref_id: str,
        channel_id: str | None,
        name: str,
        provider: str,
        api_type: str,
        base_url: str,
        api_key: str,
        timeout: int,
        max_retries: int,
        weight: float,
        upstream_model_id: str,
        ref_type: str,
        inline_config: dict | None = None,
        custom_headers: dict | None = None,
    ):
        self.ref_id = ref_id
        self.channel_id = channel_id
        self.name = name
        self.provider = provider
        self.api_type = api_type
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.weight = weight
        self.upstream_model_id = upstream_model_id
        self.ref_type = ref_type
        self.inline_config = inline_config
        self.custom_headers = custom_headers or {}


async def get_model_channels(model_name: str, session: AsyncSession) -> list[ChannelInfo]:
    result = await session.execute(
        select(ModelConfig).where(ModelConfig.name == model_name)
    )
    model = result.scalar_one_or_none()
    if not model:
        return []

    ref_result = await session.execute(
        select(ModelChannelRef)
        .where(ModelChannelRef.model_id == model.id)
        .order_by(ModelChannelRef.priority.asc())
    )
    refs = ref_result.scalars().all()

    channels = []
    for ref in refs:
        if ref.type == "reference" and ref.channel_id:
            ch_result = await session.execute(
                select(Channel).where(Channel.id == ref.channel_id)
            )
            ch = ch_result.scalar_one_or_none()
            if ch:
                from app.core.encryption import key_encryption
                channels.append(
                    ChannelInfo(
                        ref_id=ref.id,
                        channel_id=ch.id,
                        name=ch.name,
                        provider=ch.provider,
                        api_type=ch.api_type or _default_api_type_for_provider(ch.provider),
                        base_url=ch.base_url,
                        api_key=key_encryption.decrypt(ch.encrypted_api_key),
                        timeout=ch.timeout or settings.default_channel_timeout,
                        max_retries=ch.max_retries or settings.default_max_retries,
                        weight=ref.weight if ref.weight is not None else ch.weight,
                        upstream_model_id=ref.upstream_model_id or "",
                        ref_type="reference",
                        custom_headers=ch.custom_headers,
                    )
                )
        elif ref.type == "inline" and ref.inline_config:
            inline = ref.inline_config
            from app.core.encryption import key_encryption
            enc_api_key = inline.get("api_key", "")
            channels.append(
                ChannelInfo(
                    ref_id=ref.id,
                    channel_id=None,
                    name=inline.get("name", "inline"),
                    provider=inline.get("provider", "openai"),
                    api_type=inline.get("api_type") or _default_api_type_for_provider(inline.get("provider", "openai")),
                    base_url=inline.get("base_url", ""),
                    api_key=key_encryption.decrypt(enc_api_key) if enc_api_key else "",
                    timeout=inline.get("timeout", settings.default_channel_timeout),
                    max_retries=inline.get("max_retries", settings.default_max_retries),
                    weight=ref.weight,
                    upstream_model_id=ref.upstream_model_id or inline.get("upstream_model_id", ""),
                    ref_type="inline",
                    inline_config=inline,
                    custom_headers=inline.get("custom_headers"),
                )
            )

    return channels


def _default_api_type_for_provider(provider: str) -> str:
    if provider == "anthropic":
        return "claude"
    return "openai"


async def filter_healthy_channels(channels: list[ChannelInfo]) -> list[ChannelInfo]:
    healthy = []
    for ch in channels:
        if ch.channel_id:
            if await is_circuit_open(ch.channel_id):
                continue
            if not await should_allow_request(ch.channel_id):
                continue
            health = await get_channel_health_status(ch.channel_id)
            if health == "unhealthy":
                continue

        healthy.append(ch)
    return healthy


async def apply_routing_strategy(
    channels: list[ChannelInfo],
    strategy: str,
    custom_js: str = "",
    context: dict | None = None,
) -> list[ChannelInfo]:
    if not channels:
        return []

    if strategy == "random":
        shuffled = list(channels)
        random.shuffle(shuffled)
        return shuffled

    elif strategy == "weighted":
        return _weighted_order(channels)

    elif strategy == "custom_js":
        return await _execute_custom_js(channels, custom_js, context or {})

    else:
        return list(channels)


def _weighted_order(channels: list[ChannelInfo]) -> list[ChannelInfo]:
    remaining = list(channels)
    ordered = []

    while remaining:
        total_weight = sum(ch.weight for ch in remaining)
        if total_weight <= 0:
            ordered.extend(remaining)
            break

        r = random.uniform(0, total_weight)
        cumulative = 0
        selected_idx = 0
        for i, ch in enumerate(remaining):
            cumulative += ch.weight
            if r <= cumulative:
                selected_idx = i
                break

        ordered.append(remaining.pop(selected_idx))

    return ordered


async def _execute_custom_js(
    channels: list[ChannelInfo],
    custom_js: str,
    context: dict,
) -> list[ChannelInfo]:
    import asyncio
    import subprocess

    try:
        channel_data = []
        for ch in channels:
            channel_data.append({
                "ref_id": ch.ref_id,
                "channel_id": ch.channel_id,
                "name": ch.name,
                "provider": ch.provider,
                "weight": ch.weight,
            })

        script_input = json.dumps({
            "channels": channel_data,
            "context": context,
        })

        node_script = f"""
        const input = JSON.parse(process.argv[1]);
        const channels = input.channels;
        const ctx = input.context;

        function route(channels, ctx) {{
            {custom_js}
        }}

        const result = route(channels, ctx);
        console.log(JSON.stringify(Array.isArray(result) ? result : channels));
        """

        proc = await asyncio.create_subprocess_exec(
            "node", "-e", node_script,
            script_input,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=0.02
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("Custom JS script timed out, falling back to default strategy")
            return list(channels)

        if proc.returncode == 0 and stdout:
            try:
                ordered_ids = json.loads(stdout.decode().strip())
                if isinstance(ordered_ids, list) and len(ordered_ids) > 0:
                    id_map = {}
                    for ch in channels:
                        id_map[ch.ref_id] = ch
                        if ch.channel_id:
                            id_map[ch.channel_id] = ch

                    ordered = []
                    seen = set()
                    for oid in ordered_ids:
                        if oid in id_map and id_map[oid].ref_id not in seen:
                            ordered.append(id_map[oid])
                            seen.add(id_map[oid].ref_id)

                    for ch in channels:
                        if ch.ref_id not in seen:
                            ordered.append(ch)

                    return ordered
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Custom JS returned invalid result: {e}")

        if stderr:
            logger.warning(f"Custom JS stderr: {stderr.decode()[:200]}")

    except Exception as e:
        logger.error(f"Custom JS execution error: {e}")

    return list(channels)


async def route_request(
    model_name: str,
    api_type: str,
    request_body: dict,
) -> tuple[list[ChannelInfo], ModelConfig | None]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.name == model_name)
        )
        model_config = result.scalar_one_or_none()

        if not model_config:
            return [], None

        channels = await get_model_channels(model_name, session)

    healthy_channels = await filter_healthy_channels(channels)

    if not healthy_channels:
        logger.warning(
            f"No healthy channels available for model {model_name}",
            extra={"trace_id": "routing"},
        )
        return [], model_config

    ordered_channels = await apply_routing_strategy(
        healthy_channels,
        model_config.routing_strategy,
        model_config.custom_js or "",
        {"model": model_name, "api_type": api_type, "request": request_body},
    )

    if not model_config.failover_enabled:
        return ordered_channels[:1], model_config

    return ordered_channels, model_config
