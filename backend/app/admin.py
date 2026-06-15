import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.core.encryption import key_encryption
from app.core.http_debug import log_upstream_request, log_upstream_response
from app.core.logging import get_logger
from app.models.channel import Channel
from app.models.model_config import ModelConfig
from app.models.model_channel_ref import ModelChannelRef
from app.models.request_log import RequestLog
from app.models.plugin import Plugin as PluginModel
from app.models.api_key import ApiKey
from app.services.health_checker import get_channel_health_status
from app.services.cache_service import get_cache_stats, delete_cache_for_model, clear_all_cache
from app.services.circuit_breaker import reset_circuit
from app.core.config import config_manager, CONFIG_META, SENSITIVE_KEYS
from app.core.response import success_response, error_response
from app.adapters.generic_adapter import get_adapter
from app.adapters.base_adapter import merge_custom_headers
from app.services.request_transformer import normalize_channel_api_type

logger = get_logger(__name__)
admin_router = APIRouter()

@admin_router.post("/auth/verify")
async def verify_admin():
    return success_response(detail_result={"verified": True})

@admin_router.post("/playground")
async def playground_proxy(request: Request, background_tasks: BackgroundTasks):
    from app.services.gateway_handler import handle_gateway_request

    body = await request.json()
    api_type = body.pop("_api_type", "openai")

    request.state.api_key_info = {
        "id": None,
        "key_hash": "admin_playground",
        "max_tokens": None,
        "used_tokens": 0,
        "allowed_models": None,
    }

    request._body = json.dumps(body).encode()

    return await handle_gateway_request(request, background_tasks, api_type)

class ChannelTestRequest(BaseModel):
    model: str
    message: str = "Hi, please respond with a short greeting to confirm you are working."

class ChannelCreate(BaseModel):
    name: str
    provider: str = "openai"
    api_type: Optional[str] = None
    base_url: str
    api_key: str = ""
    timeout: int = 30
    max_retries: int = 2
    default_weight: float = 1.0
    upstream_models: list[str] = Field(default_factory=list)
    custom_headers: Optional[dict] = None

class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    api_type: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: Optional[int] = None
    max_retries: Optional[int] = None
    default_weight: Optional[float] = None
    upstream_models: Optional[list[str]] = None
    custom_headers: Optional[dict] = None

THINKING_EFFORTS = {"none", "low", "medium", "high"}
CLAUDE_THINKING_MODES = {"adaptive", "enabled", "disabled"}

def _validate_model_thinking_fields(data: BaseModel) -> None:
    values = data.model_dump(exclude_unset=True)
    effort = values.get("default_thinking_effort")
    if effort is not None and effort not in THINKING_EFFORTS:
        raise HTTPException(status_code=400, detail="default_thinking_effort must be one of none, low, medium, high")
    mode = values.get("claude_thinking_mode")
    if mode is not None and mode not in CLAUDE_THINKING_MODES:
        raise HTTPException(status_code=400, detail="claude_thinking_mode must be one of adaptive, enabled, disabled")

class ModelCreate(BaseModel):
    name: str
    display_name: str = ""
    routing_strategy: str = "default"
    custom_js: str = ""
    failover_enabled: bool = True
    is_listed: bool = True
    supports_thinking: bool = False
    default_thinking_effort: str = "none"
    claude_thinking_mode: str = "adaptive"
    enable_cache: bool = False
    cache_ttl_seconds: int = 3600
    cache_key_exclude_fields: str = "[]"

class ModelUpdate(BaseModel):
    display_name: Optional[str] = None
    routing_strategy: Optional[str] = None
    custom_js: Optional[str] = None
    failover_enabled: Optional[bool] = None
    is_listed: Optional[bool] = None
    supports_thinking: Optional[bool] = None
    default_thinking_effort: Optional[str] = None
    claude_thinking_mode: Optional[str] = None
    enable_cache: Optional[bool] = None
    cache_ttl_seconds: Optional[int] = None
    cache_key_exclude_fields: Optional[str] = None

class ChannelRefCreate(BaseModel):
    channel_id: Optional[str] = None
    priority: int = 0
    weight: Optional[float] = None
    upstream_model_id: str = ""
    type: str = "reference"
    inline_config: Optional[dict] = None

def _public_inline_config(inline_config: Optional[dict]) -> Optional[dict]:
    if not inline_config:
        return inline_config
    safe_config = dict(inline_config)
    safe_config.pop("api_key", None)
    return safe_config

def _prepare_inline_config(inline_config: Optional[dict]) -> dict:
    config = dict(inline_config or {})
    provider = config.get("provider", "openai")
    config["api_type"] = _validate_channel_api_type(config.get("api_type"), provider)
    api_key = config.get("api_key")
    if api_key:
        config["api_key"] = key_encryption.encrypt(api_key)
    return config


def _default_api_type_for_provider(provider: str) -> str:
    if provider == "anthropic":
        return "claude"
    return "openai"


def _validate_channel_api_type(api_type: Optional[str], provider: str) -> str:
    if api_type is not None and api_type not in {"openai", "responses", "claude", "auto"}:
        raise HTTPException(status_code=400, detail="api_type must be openai, responses, claude or auto")
    if provider == "anthropic" and api_type not in (None, "claude"):
        raise HTTPException(status_code=400, detail="anthropic channels must use claude api_type")
    if provider in ("openai", "azure", "google") and api_type == "claude":
        raise HTTPException(status_code=400, detail=f"{provider} channels cannot use claude api_type")
    return normalize_channel_api_type(api_type or _default_api_type_for_provider(provider), provider)


async def _fetch_channel_upstream_models(channel: Channel) -> list[str]:
    adapter = get_adapter(channel.provider)
    api_key = key_encryption.decrypt(channel.encrypted_api_key)
    headers = adapter.get_headers(api_key)
    headers = merge_custom_headers(headers, channel.custom_headers)
    api_type = normalize_channel_api_type(channel.api_type, channel.provider)
    url = f"{channel.base_url.rstrip('/')}/v1/models"

    async with httpx.AsyncClient(timeout=channel.timeout or 30) as client:
        log_upstream_request(logger, "GET", url, trace_id="admin_sync_models", channel=channel.name)
        response = await client.get(url, headers=headers)
    log_upstream_response(logger, "GET", url, response.status_code, response.text, "admin_sync_models", channel.name)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch upstream models: {response.text[:500]}",
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Upstream returned invalid JSON") from exc

    candidates = payload.get("data", payload.get("models", []))
    models = []
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, str):
                models.append(item)
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name") or item.get("model")
                if model_id:
                    models.append(str(model_id))

    return sorted(set(models))

async def _resolve_ref_weight(data: ChannelRefCreate, db: AsyncSession) -> float:
    if data.weight is not None:
        return data.weight
    if data.type == "reference" and data.channel_id:
        result = await db.execute(select(Channel.weight).where(Channel.id == data.channel_id))
        channel_weight = result.scalar_one_or_none()
        if channel_weight is not None:
            return channel_weight
    return 1.0

class PluginCreate(BaseModel):
    name: str
    hook_type: str
    priority: int = 0
    enabled: bool = True
    module_path: str
    config: Optional[dict] = None

class PluginUpdate(BaseModel):
    name: Optional[str] = None
    hook_type: Optional[str] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    module_path: Optional[str] = None
    config: Optional[dict] = None

@admin_router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    last_hour = now - timedelta(hours=1)

    total_result = await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.created_at >= last_hour)
    )
    total_requests = total_result.scalar() or 0

    error_result = await db.execute(
        select(func.count(RequestLog.id)).where(
            and_(RequestLog.created_at >= last_hour, RequestLog.status_code >= 400)
        )
    )
    error_count = error_result.scalar() or 0
    error_rate = round(error_count / total_requests * 100, 2) if total_requests > 0 else 0.0

    channel_result = await db.execute(select(Channel))
    channels = channel_result.scalars().all()
    channel_health = []
    for ch in channels:
        health = await get_channel_health_status(ch.id)
        channel_health.append({
            "id": ch.id, "name": ch.name, "provider": ch.provider,
            "health_status": health, "circuit_state": ch.circuit_state,
        })
    healthy_channel_count = sum(1 for ch in channel_health if ch["health_status"] == "healthy")

    cache_stats = await get_cache_stats()
    total_cache_hit = sum(m.get("hit", 0) for m in cache_stats.get("models", []))
    total_cache_miss = sum(m.get("miss", 0) for m in cache_stats.get("models", []))
    total_cache = total_cache_hit + total_cache_miss
    cache_hit_rate = round(total_cache_hit / total_cache * 100, 2) if total_cache > 0 else 0.0

    token_hour_result = await db.execute(
        select(
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0),
            func.coalesce(func.sum(RequestLog.completion_tokens), 0),
            func.coalesce(func.sum(RequestLog.total_tokens), 0),
            func.coalesce(func.sum(RequestLog.cache_tokens), 0),
        ).where(RequestLog.created_at >= last_hour)
    )
    prompt_tokens_hour, completion_tokens_hour, total_tokens_hour, cache_tokens_hour = token_hour_result.one()

    token_total_result = await db.execute(
        select(func.coalesce(func.sum(RequestLog.total_tokens), 0))
    )
    total_tokens_all = token_total_result.scalar() or 0

    hourly_result = await db.execute(
        select(
            func.date_trunc("hour", RequestLog.created_at).label("bucket"),
            func.count(RequestLog.id).label("request_count"),
            func.count(RequestLog.id).filter(RequestLog.status_code >= 400).label("error_count"),
            func.count(func.distinct(RequestLog.selected_channel_id))
            .filter(
                and_(
                    RequestLog.status_code < 400,
                    RequestLog.selected_channel_id.isnot(None),
                    RequestLog.selected_channel_id.notin_(["", "cache", "inline"]),
                )
            )
            .label("healthy_channels"),
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(RequestLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(RequestLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(RequestLog.cache_tokens), 0).label("cache_tokens"),
        )
        .where(RequestLog.created_at >= now - timedelta(hours=24))
        .group_by("bucket")
        .order_by("bucket")
    )
    hourly_tokens = [
        {
            "time": row.bucket.isoformat() if row.bucket else "",
            "request_count": int(row.request_count or 0),
            "error_count": int(row.error_count or 0),
            "healthy_channels": int(row.healthy_channels or 0),
            "prompt_tokens": int(row.prompt_tokens or 0),
            "completion_tokens": int(row.completion_tokens or 0),
            "total_tokens": int(row.total_tokens or 0),
            "cache_tokens": int(row.cache_tokens or 0),
        }
        for row in hourly_result.all()
    ]

    daily_result = await db.execute(
        select(
            func.date_trunc("day", RequestLog.created_at).label("bucket"),
            func.count(RequestLog.id).label("request_count"),
            func.count(RequestLog.id).filter(RequestLog.status_code >= 400).label("error_count"),
            func.count(func.distinct(RequestLog.selected_channel_id))
            .filter(
                and_(
                    RequestLog.status_code < 400,
                    RequestLog.selected_channel_id.isnot(None),
                    RequestLog.selected_channel_id.notin_(["", "cache", "inline"]),
                )
            )
            .label("healthy_channels"),
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(RequestLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(RequestLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(RequestLog.cache_tokens), 0).label("cache_tokens"),
        )
        .where(RequestLog.created_at >= now - timedelta(days=14))
        .group_by("bucket")
        .order_by("bucket")
    )
    daily_tokens = [
        {
            "time": row.bucket.isoformat() if row.bucket else "",
            "request_count": int(row.request_count or 0),
            "error_count": int(row.error_count or 0),
            "healthy_channels": int(row.healthy_channels or 0),
            "prompt_tokens": int(row.prompt_tokens or 0),
            "completion_tokens": int(row.completion_tokens or 0),
            "total_tokens": int(row.total_tokens or 0),
            "cache_tokens": int(row.cache_tokens or 0),
        }
        for row in daily_result.all()
    ]

    return success_response(detail_result={
        "total_requests": total_requests,
        "error_rate": error_rate,
        "channel_health": channel_health,
        "healthy_channels": healthy_channel_count,
        "total_channels": len(channel_health),
        "cache_hit_rate": cache_hit_rate,
        "cache_stats": cache_stats,
        "token_stats": {
            "prompt_tokens_last_hour": int(prompt_tokens_hour or 0),
            "completion_tokens_last_hour": int(completion_tokens_hour or 0),
            "total_tokens_last_hour": int(total_tokens_hour or 0),
            "cache_tokens_last_hour": int(cache_tokens_hour or 0),
            "total_tokens_all": int(total_tokens_all or 0),
        },
        "token_charts": {
            "hourly": hourly_tokens,
            "daily": daily_tokens,
        },
        "stats_charts": {
            "hourly": hourly_tokens,
            "daily": daily_tokens,
        },
    })

@admin_router.get("/channels")
async def list_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).order_by(desc(Channel.created_at)))
    channels = result.scalars().all()

    channel_list = []
    for ch in channels:
        health = await get_channel_health_status(ch.id)
        channel_list.append({
            "id": ch.id, "name": ch.name, "provider": ch.provider,
            "api_type": ch.api_type or _default_api_type_for_provider(ch.provider),
            "base_url": ch.base_url, "timeout": ch.timeout,
            "max_retries": ch.max_retries, "default_weight": ch.weight,
            "upstream_models": ch.upstream_models or [],
            "custom_headers": ch.custom_headers or {},
            "health_status": health,
            "circuit_state": ch.circuit_state,
            "created_at": ch.created_at.isoformat() if ch.created_at else "",
            "updated_at": ch.updated_at.isoformat() if ch.updated_at else "",
        })
    return success_response(detail_result={"data": channel_list, "total": len(channel_list)})

@admin_router.get("/channels/{channel_id}")
async def get_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    health = await get_channel_health_status(ch.id)
    return success_response(detail_result={
        "id": ch.id, "name": ch.name, "provider": ch.provider,
        "api_type": ch.api_type or _default_api_type_for_provider(ch.provider),
        "base_url": ch.base_url, "timeout": ch.timeout,
        "max_retries": ch.max_retries, "default_weight": ch.weight,
        "upstream_models": ch.upstream_models or [],
        "custom_headers": ch.custom_headers or {},
        "health_status": health,
        "circuit_state": ch.circuit_state,
        "created_at": ch.created_at.isoformat() if ch.created_at else "",
        "updated_at": ch.updated_at.isoformat() if ch.updated_at else "",
    })

@admin_router.post("/channels")
async def create_channel(data: ChannelCreate, db: AsyncSession = Depends(get_db)):
    encrypted_key = key_encryption.encrypt(data.api_key)
    api_type = _validate_channel_api_type(data.api_type, data.provider)
    channel = Channel(
        id=str(uuid.uuid4()),
        name=data.name,
        provider=data.provider,
        api_type=api_type,
        base_url=data.base_url,
        encrypted_api_key=encrypted_key,
        timeout=data.timeout,
        max_retries=data.max_retries,
        weight=data.default_weight,
        upstream_models=data.upstream_models,
        custom_headers=data.custom_headers,
    )
    db.add(channel)
    await db.commit()
    return success_response(detail_result={"id": channel.id, "name": channel.name, "message": "Channel created"})

@admin_router.put("/channels/{channel_id}")
async def update_channel(channel_id: str, data: ChannelUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    if data.name is not None:
        ch.name = data.name
    next_provider = data.provider or ch.provider
    next_api_type = data.api_type if data.api_type is not None else (
        _default_api_type_for_provider(next_provider) if data.provider is not None else ch.api_type
    )
    validated_api_type = _validate_channel_api_type(next_api_type, next_provider)
    if data.provider is not None:
        ch.provider = data.provider
    ch.api_type = validated_api_type
    if data.base_url is not None:
        ch.base_url = data.base_url
    if data.api_key is not None:
        ch.encrypted_api_key = key_encryption.encrypt(data.api_key)
    if data.timeout is not None:
        ch.timeout = data.timeout
    if data.max_retries is not None:
        ch.max_retries = data.max_retries
    if data.default_weight is not None:
        ch.weight = data.default_weight
    if data.upstream_models is not None:
        ch.upstream_models = data.upstream_models
    if data.custom_headers is not None:
        ch.custom_headers = data.custom_headers

    db.add(ch)
    await db.commit()
    return success_response(detail_result={"id": ch.id, "message": "Channel updated"})

@admin_router.post("/channels/{channel_id}/sync-models")
async def sync_channel_models(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    models = await _fetch_channel_upstream_models(ch)
    ch.upstream_models = models
    db.add(ch)
    await db.commit()
    return success_response(detail_result={"id": ch.id, "upstream_models": models, "total": len(models)})

@admin_router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: str, data: ChannelTestRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    api_key = key_encryption.decrypt(ch.encrypted_api_key)
    api_type = normalize_channel_api_type(ch.api_type, ch.provider)
    adapter = get_adapter(ch.provider)
    timeout = ch.timeout or 30

    if api_type == "claude":
        request_body = {
            "model": data.model,
            "messages": [{"role": "user", "content": data.message}],
            "max_tokens": 64,
        }
    elif api_type == "responses":
        request_body = {
            "model": data.model,
            "input": data.message,
            "max_output_tokens": 64,
        }
    else:
        request_body = {
            "model": data.model,
            "messages": [{"role": "user", "content": data.message}],
            "max_tokens": 64,
        }

    upstream_api_type = api_type
    provider_request = adapter.convert_request(request_body, upstream_api_type)
    headers = adapter.get_headers(api_key)
    headers = merge_custom_headers(headers, ch.custom_headers)
    url = adapter.get_url(ch.base_url, upstream_api_type)

    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            log_upstream_request(logger, "POST", url, provider_request, trace_id="admin_test_channel", channel=ch.name)
            resp = await client.post(url, json=provider_request, headers=headers)
            elapsed = (time.time() - start_time) * 1000
            log_upstream_response(logger, "POST", url, resp.status_code, resp.text[:500], "admin_test_channel", ch.name)

        if resp.status_code >= 400:
            error_message = resp.text[:500]
            try:
                error_json = resp.json()
                if isinstance(error_json, dict):
                    error_message = json.dumps(error_json, ensure_ascii=False)[:500]
            except Exception:
                pass
            return success_response(detail_result={
                "success": False,
                "model": data.model,
                "reply": "",
                "error": error_message,
                "status_code": resp.status_code,
                "latency_ms": round(elapsed, 1),
            })

        response_body = resp.json()
        response = adapter.convert_response(response_body, upstream_api_type, provider_request)
        reply_text = _extract_reply_text(response, api_type)

        return success_response(detail_result={
            "success": True,
            "model": data.model,
            "reply": reply_text[:500],
            "latency_ms": round(elapsed, 1),
        })

    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        return success_response(detail_result={
            "success": False,
            "model": data.model,
            "reply": "",
            "error": str(e)[:500],
            "status_code": getattr(e, "status_code", 500),
            "latency_ms": round(elapsed, 1),
        })

def _extract_reply_text(response: dict, api_type: str) -> str:
    if api_type == "claude":
        content = response.get("content", [])
        if isinstance(content, list):
            return "".join(item.get("text", "") for item in content if isinstance(item, dict))
        return str(content)
    if api_type == "responses":
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        output = response.get("output", [])
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    for part in item.get("content", []):
                        if isinstance(part, dict):
                            return part.get("text", part.get("output_text", ""))
        return ""
    choices = response.get("choices", [])
    if choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message", {})
        return message.get("content", "")
    return ""

@admin_router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")

    refs_result = await db.execute(
        select(ModelChannelRef).where(ModelChannelRef.channel_id == channel_id)
    )
    for ref in refs_result.scalars().all():
        await db.delete(ref)

    await db.delete(ch)
    await db.commit()

    return success_response(detail_result={"message": "Channel deleted"})

@admin_router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).order_by(desc(ModelConfig.created_at)))
    models = result.scalars().all()

    model_list = []
    for m in models:
        refs_result = await db.execute(
            select(ModelChannelRef).where(ModelChannelRef.model_id == m.id)
        )
        refs = refs_result.scalars().all()
        channel_refs = []
        for ref in refs:
            channel_name = ""
            if ref.type == "reference" and ref.channel_id:
                ch_result = await db.execute(
                    select(Channel.name).where(Channel.id == ref.channel_id)
                )
                ch_name = ch_result.scalar_one_or_none()
                channel_name = ch_name or ""
            elif ref.type == "inline":
                channel_name = ref.inline_config.get("name", "inline") if ref.inline_config else "inline"

            channel_refs.append({
                "id": ref.id,
                "channel_id": ref.channel_id,
                "channel_name": channel_name,
                "priority": ref.priority,
                "weight": ref.weight,
                "upstream_model_id": ref.upstream_model_id,
                "type": ref.type,
                "inline_config": _public_inline_config(ref.inline_config),
            })

        model_list.append({
            "id": m.id,
            "name": m.name,
            "display_name": m.display_name,
            "routing_strategy": m.routing_strategy,
            "custom_js": m.custom_js,
            "failover_enabled": m.failover_enabled,
            "is_listed": m.is_listed,
            "supports_thinking": m.supports_thinking,
            "default_thinking_effort": m.default_thinking_effort,
            "claude_thinking_mode": m.claude_thinking_mode,
            "enable_cache": m.enable_cache,
            "cache_ttl_seconds": m.cache_ttl_seconds,
            "cache_key_exclude_fields": m.cache_key_exclude_fields,
            "channel_refs": channel_refs,
            "created_at": m.created_at.isoformat() if m.created_at else "",
            "updated_at": m.updated_at.isoformat() if m.updated_at else "",
        })

    return success_response(detail_result={"data": model_list, "total": len(model_list)})

@admin_router.get("/models/{model_id}")
async def get_model(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    return success_response(detail_result={
        "id": m.id, "name": m.name, "display_name": m.display_name,
        "routing_strategy": m.routing_strategy,
        "custom_js": m.custom_js, "failover_enabled": m.failover_enabled,
        "is_listed": m.is_listed,
        "supports_thinking": m.supports_thinking,
        "default_thinking_effort": m.default_thinking_effort,
        "claude_thinking_mode": m.claude_thinking_mode,
        "enable_cache": m.enable_cache, "cache_ttl_seconds": m.cache_ttl_seconds,
        "cache_key_exclude_fields": m.cache_key_exclude_fields,
        "created_at": m.created_at.isoformat() if m.created_at else "",
        "updated_at": m.updated_at.isoformat() if m.updated_at else "",
    })

@admin_router.post("/models")
async def create_model(data: ModelCreate, db: AsyncSession = Depends(get_db)):
    _validate_model_thinking_fields(data)
    existing = await db.execute(select(ModelConfig).where(ModelConfig.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Model '{data.name}' already exists")

    model = ModelConfig(
        id=str(uuid.uuid4()),
        name=data.name,
        display_name=data.display_name,
        routing_strategy=data.routing_strategy,
        custom_js=data.custom_js,
        failover_enabled=data.failover_enabled,
        is_listed=data.is_listed,
        supports_thinking=data.supports_thinking,
        default_thinking_effort=data.default_thinking_effort,
        claude_thinking_mode=data.claude_thinking_mode,
        enable_cache=data.enable_cache,
        cache_ttl_seconds=data.cache_ttl_seconds,
        cache_key_exclude_fields=data.cache_key_exclude_fields,
    )
    db.add(model)
    await db.commit()
    return success_response(detail_result={"id": model.id, "name": model.name, "message": "Model created"})

@admin_router.put("/models/{model_id}")
async def update_model(model_id: str, data: ModelUpdate, db: AsyncSession = Depends(get_db)):
    _validate_model_thinking_fields(data)
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")

    update_dict = data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(m, key, value)

    db.add(m)
    await db.commit()
    return success_response(detail_result={"id": m.id, "message": "Model updated"})

@admin_router.delete("/models/{model_id}")
async def delete_model(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")

    refs_result = await db.execute(
        select(ModelChannelRef).where(ModelChannelRef.model_id == model_id)
    )
    for ref in refs_result.scalars().all():
        await db.delete(ref)

    await db.delete(m)
    await db.commit()
    return success_response(detail_result={"message": "Model deleted"})

@admin_router.get("/models/{model_id}/channels")
async def list_model_channels(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ModelChannelRef)
        .where(ModelChannelRef.model_id == model_id)
        .order_by(ModelChannelRef.priority.asc())
    )
    refs = result.scalars().all()
    ref_list = []
    for ref in refs:
        channel_name = ""
        channel_default_weight = None
        if ref.type == "reference" and ref.channel_id:
            ch_result = await db.execute(
                select(Channel.name, Channel.weight).where(Channel.id == ref.channel_id)
            )
            row = ch_result.one_or_none()
            if row:
                channel_name = row._mapping["name"]
                channel_default_weight = row._mapping["weight"]
        elif ref.type == "inline":
            channel_name = ref.inline_config.get("name", "inline") if ref.inline_config else "inline"

        ref_list.append({
            "id": ref.id, "channel_id": ref.channel_id, "channel_name": channel_name,
            "priority": ref.priority, "weight": ref.weight, "type": ref.type,
            "upstream_model_id": ref.upstream_model_id,
            "inline_config": _public_inline_config(ref.inline_config),
            "channel_default_weight": channel_default_weight,
        })

    return success_response(detail_result={"data": ref_list})

@admin_router.post("/models/{model_id}/channels")
async def add_model_channel(model_id: str, data: ChannelRefCreate, db: AsyncSession = Depends(get_db)):
    model_result = await db.execute(select(ModelConfig).where(ModelConfig.id == model_id))
    if not model_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Model not found")
    if data.type not in ("reference", "inline"):
        raise HTTPException(status_code=400, detail="type must be reference or inline")
    if data.type == "reference" and not data.channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required for reference target")
    if data.type == "inline" and not data.inline_config:
        raise HTTPException(status_code=400, detail="inline_config is required for inline target")
    if not data.upstream_model_id:
        raise HTTPException(status_code=400, detail="upstream_model_id is required")

    ref = ModelChannelRef(
        id=str(uuid.uuid4()),
        model_id=model_id,
        channel_id=data.channel_id if data.type == "reference" else None,
        priority=data.priority,
        weight=await _resolve_ref_weight(data, db),
        upstream_model_id=data.upstream_model_id,
        type=data.type,
        inline_config=_prepare_inline_config(data.inline_config) if data.type == "inline" else None,
    )
    db.add(ref)
    await db.commit()
    return success_response(detail_result={"id": ref.id, "message": "Channel reference added"})

@admin_router.put("/models/{model_id}/channels/{ref_id}")
async def update_model_channel(
    model_id: str, ref_id: str, data: ChannelRefCreate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ModelChannelRef).where(
            and_(ModelChannelRef.id == ref_id, ModelChannelRef.model_id == model_id)
        )
    )
    ref = result.scalar_one_or_none()
    if not ref:
        raise HTTPException(status_code=404, detail="Channel reference not found")
    if data.type not in ("reference", "inline"):
        raise HTTPException(status_code=400, detail="type must be reference or inline")
    if data.type == "reference" and not data.channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required for reference target")
    if data.type == "inline" and not data.inline_config:
        raise HTTPException(status_code=400, detail="inline_config is required for inline target")
    if not data.upstream_model_id:
        raise HTTPException(status_code=400, detail="upstream_model_id is required")

    ref.channel_id = data.channel_id if data.type == "reference" else None
    ref.priority = data.priority
    ref.weight = await _resolve_ref_weight(data, db)
    ref.upstream_model_id = data.upstream_model_id
    ref.type = data.type
    ref.inline_config = _prepare_inline_config(data.inline_config) if data.type == "inline" else None

    db.add(ref)
    await db.commit()
    return success_response(detail_result={"message": "Channel reference updated"})

@admin_router.delete("/models/{model_id}/channels/{ref_id}")
async def delete_model_channel(model_id: str, ref_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ModelChannelRef).where(
            and_(ModelChannelRef.id == ref_id, ModelChannelRef.model_id == model_id)
        )
    )
    ref = result.scalar_one_or_none()
    if not ref:
        raise HTTPException(status_code=404, detail="Channel reference not found")
    await db.delete(ref)
    await db.commit()
    return success_response(detail_result={"message": "Channel reference deleted"})

@admin_router.get("/logs")
async def list_logs(
    api_type: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    status: Optional[int] = Query(None),
    cache_hit: Optional[bool] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    conditions = []

    if api_type:
        conditions.append(RequestLog.api_type == api_type)
    if model:
        conditions.append(RequestLog.model == model)
    if channel_id:
        conditions.append(RequestLog.selected_channel_id == channel_id)
    if status is not None:
        conditions.append(RequestLog.status_code == status)
    if cache_hit is not None:
        conditions.append(RequestLog.cache_hit == cache_hit)
    if from_date:
        try:
            dt = datetime.fromisoformat(from_date)
            conditions.append(RequestLog.created_at >= dt)
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.fromisoformat(to_date)
            conditions.append(RequestLog.created_at <= dt)
        except ValueError:
            pass

    query = select(RequestLog)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(desc(RequestLog.created_at))

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return success_response(detail_result={
        "data": [
            {
                "id": log.id,
                "trace_id": log.trace_id,
                "api_type": log.api_type,
                "model": log.model,
                "selected_channel_name": log.selected_channel_name,
                "upstream_url": log.upstream_url,
                "latency_ms": log.latency_ms,
                "status_code": log.status_code,
                "error_message": log.error_message,
                "thinking_effort": log.thinking_effort or "none",
                "cache_hit": log.cache_hit,
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "total_tokens": log.total_tokens,
                "cache_tokens": log.cache_tokens,
                "request_body": log.request_body,
                "response_body": log.response_body,
                "input_content": log.input_content,
                "output_content": log.output_content,
                "created_at": log.created_at.isoformat() if log.created_at else "",
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    })

@admin_router.get("/cache/stats")
async def cache_stats():
    return success_response(detail_result=await get_cache_stats())

@admin_router.post("/cache/clear")
async def clear_cache(model: Optional[str] = Query(None)):
    if model:
        await delete_cache_for_model(model)
        return success_response(detail_result={"message": f"Cache cleared for model '{model}'"})
    else:
        await clear_all_cache()
        return success_response(detail_result={"message": "All cache cleared"})

@admin_router.get("/plugins")
async def list_plugins(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PluginModel).order_by(desc(PluginModel.created_at)))
    plugins = result.scalars().all()
    return success_response(detail_result={
        "data": [
            {
                "id": p.id, "name": p.name, "hook_type": p.hook_type,
                "priority": p.priority, "enabled": p.enabled,
                "module_path": p.module_path, "config": p.config,
                "created_at": p.created_at.isoformat() if p.created_at else "",
            }
            for p in plugins
        ]
    })

@admin_router.post("/plugins")
async def create_plugin(data: PluginCreate, db: AsyncSession = Depends(get_db)):
    plugin = PluginModel(
        id=str(uuid.uuid4()),
        name=data.name,
        hook_type=data.hook_type,
        priority=data.priority,
        enabled=data.enabled,
        module_path=data.module_path,
        config=data.config,
    )
    db.add(plugin)
    await db.commit()
    return success_response(detail_result={"id": plugin.id, "message": "Plugin created"})

@admin_router.put("/plugins/{plugin_id}")
async def update_plugin(plugin_id: str, data: PluginUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PluginModel).where(PluginModel.id == plugin_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Plugin not found")

    update_dict = data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(p, key, value)

    db.add(p)
    await db.commit()
    return success_response(detail_result={"message": "Plugin updated"})

@admin_router.delete("/plugins/{plugin_id}")
async def delete_plugin(plugin_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PluginModel).where(PluginModel.id == plugin_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Plugin not found")
    await db.delete(p)
    await db.commit()
    return success_response(detail_result={"message": "Plugin deleted"})

@admin_router.post("/plugins/{plugin_id}/toggle")
async def toggle_plugin(plugin_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PluginModel).where(PluginModel.id == plugin_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Plugin not found")
    p.enabled = not p.enabled
    db.add(p)
    await db.commit()
    return success_response(detail_result={"id": p.id, "enabled": p.enabled})

from app.services.api_key_service import generate_api_key as _generate_api_key, invalidate_api_key_cache


# === Configuration Management ===


class ConfigUpdateRequest(BaseModel):
    value: Any = None


@admin_router.get("/config")
async def list_config():
    return success_response(detail_result=config_manager.to_dict())


@admin_router.get("/config/{key}")
async def get_config(key: str):
    if key not in CONFIG_META:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    _, default, hot_reloadable, description = CONFIG_META[key]
    value = getattr(config_manager.settings, key, default)
    if key in SENSITIVE_KEYS and value:
        from app.core.config import mask_value as _mv
        display_value = _mv(str(value))
    else:
        display_value = value
    return success_response(detail_result={
        "key": key,
        "value": display_value,
        "type": type(value).__name__,
        "default": default,
        "hot_reloadable": hot_reloadable,
        "description": description,
        "sensitive": key in SENSITIVE_KEYS,
    })


@admin_router.put("/config/{key}")
async def update_config(key: str, data: ConfigUpdateRequest):
    if key not in CONFIG_META:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    try:
        config_manager.update(key, data.value)
        return success_response(detail_result={
            "key": key,
            "value": getattr(config_manager.settings, key),
            "message": f"'{key}' updated successfully",
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.post("/config/reload")
async def reload_config():
    config_manager.reload()
    return success_response(detail_result={
        "message": "Configuration reloaded from file",
    })

class ApiKeyCreate(BaseModel):
    name: str
    expires_at: Optional[str] = None
    max_tokens: Optional[int] = None
    allowed_models: Optional[list[str]] = None
    rate_limit: Optional[int] = None

class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    expires_at: Optional[str] = None
    max_tokens: Optional[int] = None
    allowed_models: Optional[list[str]] = None
    rate_limit: Optional[int] = None

@admin_router.get("/api-keys")
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).order_by(desc(ApiKey.created_at)))
    keys = result.scalars().all()
    return success_response(detail_result={
        "data": [
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_active": k.is_active,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "max_tokens": k.max_tokens,
                "used_tokens": k.used_tokens,
                "allowed_models": json.loads(k.allowed_models) if k.allowed_models else None,
                "rate_limit": k.rate_limit,
                "created_at": k.created_at.isoformat() if k.created_at else "",
                "updated_at": k.updated_at.isoformat() if k.updated_at else "",
            }
            for k in keys
        ],
        "total": len(keys),
    })

@admin_router.post("/api-keys")
async def create_api_key(data: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    raw_key, key_hash, key_prefix = _generate_api_key()

    expires_at = None
    if data.expires_at:
        try:
            expires_at = datetime.fromisoformat(data.expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at format, use ISO 8601")

    api_key = ApiKey(
        id=str(uuid.uuid4()),
        name=data.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        is_active=True,
        expires_at=expires_at,
        max_tokens=data.max_tokens if data.max_tokens and data.max_tokens > 0 else None,
        used_tokens=0,
        allowed_models=json.dumps(data.allowed_models) if data.allowed_models else None,
        rate_limit=data.rate_limit if data.rate_limit and data.rate_limit > 0 else None,
    )
    db.add(api_key)
    await db.commit()

    return success_response(detail_result={
        "id": api_key.id,
        "name": api_key.name,
        "key": raw_key,
        "key_prefix": key_prefix,
        "message": "API key created. Save the key now — it will not be shown again.",
    })

@admin_router.put("/api-keys/{key_id}")
async def update_api_key(key_id: str, data: ApiKeyUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    k = result.scalar_one_or_none()
    if not k:
        raise HTTPException(status_code=404, detail="API key not found")

    if data.name is not None:
        k.name = data.name
    if data.is_active is not None:
        k.is_active = data.is_active
    if data.expires_at is not None:
        if data.expires_at == "" or data.expires_at.lower() == "never":
            k.expires_at = None
        else:
            try:
                k.expires_at = datetime.fromisoformat(data.expires_at)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid expires_at format")
    if data.max_tokens is not None:
        k.max_tokens = data.max_tokens if data.max_tokens > 0 else None
    if data.allowed_models is not None:
        k.allowed_models = json.dumps(data.allowed_models) if data.allowed_models else None
    if data.rate_limit is not None:
        k.rate_limit = data.rate_limit if data.rate_limit > 0 else None

    db.add(k)
    await db.commit()

    await invalidate_api_key_cache(k.key_hash)

    return success_response(detail_result={
        "id": k.id,
        "name": k.name,
        "is_active": k.is_active,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "max_tokens": k.max_tokens,
        "used_tokens": k.used_tokens,
        "allowed_models": json.loads(k.allowed_models) if k.allowed_models else None,
        "rate_limit": k.rate_limit,
        "message": "API key updated",
    })

@admin_router.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    k = result.scalar_one_or_none()
    if not k:
        raise HTTPException(status_code=404, detail="API key not found")

    key_hash = k.key_hash
    await db.delete(k)
    await db.commit()

    await invalidate_api_key_cache(key_hash)

    return success_response(detail_result={"message": "API key deleted"})

@admin_router.post("/api-keys/{key_id}/toggle")
async def toggle_api_key(key_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    k = result.scalar_one_or_none()
    if not k:
        raise HTTPException(status_code=404, detail="API key not found")
    k.is_active = not k.is_active
    db.add(k)
    await db.commit()

    await invalidate_api_key_cache(k.key_hash)

    return success_response(detail_result={"id": k.id, "is_active": k.is_active})
