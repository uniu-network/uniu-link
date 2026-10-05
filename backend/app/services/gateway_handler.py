import asyncio
import json
import time
from typing import Any, TypedDict

import anyio
import httpx
from fastapi import Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings
from app.core.response import api_error_body, api_error_response, api_error_type, extract_error_message
from app.core.http_debug import log_upstream_request, log_upstream_response
from app.core.logging import get_logger
from app.middleware.request_id import get_trace_id
from app.services.api_key_service import increment_token_usage, check_model_access
from app.services.routing_engine import route_request, ChannelInfo
from app.services.circuit_breaker import record_success, record_failure, request_permit
from app.services.rate_limiter import check_rate_limit
from app.adapters.generic_adapter import get_adapter
from app.adapters.base_adapter import merge_custom_headers
from app.plugins.plugin_engine import plugin_engine
from app.services.request_transformer import (
    apply_default_thinking,
    get_effective_thinking_effort,
    resolve_channel_api_type,
    transform_request_body,
    transform_response_body,
    transform_stream_chunk,
)

from app.services.stream_transformer import StreamProtocolError, StreamState

logger = get_logger(__name__)

class ApiKeyLogContext(TypedDict):
    from_apikey: str
    from_apikey_name: str


class NoRetryError(Exception):

    def __init__(self, status_code: int, error_body: dict):
        self.status_code = status_code
        self.error_body = error_body
        super().__init__(json.dumps(error_body))


class UpstreamAPIError(Exception):

    def __init__(self, status_code: int, error_body: dict):
        self.status_code = status_code
        self.error_body = error_body
        super().__init__(extract_error_message(error_body))

def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

def _empty_token_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cache_tokens": 0}

def extract_token_usage(response_data: dict | None) -> dict[str, int]:
    if not isinstance(response_data, dict):
        return _empty_token_usage()

    usage = response_data.get("usage") or {}
    if not isinstance(usage, dict):
        return _empty_token_usage()

    prompt_tokens = _safe_int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
    completion_tokens = _safe_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    total_tokens = _safe_int(usage.get("total_tokens")) or (prompt_tokens + completion_tokens)
    cache_tokens = _safe_int(
        usage.get("cache_read_input_tokens", usage.get("cached_tokens", 0))
    ) + _safe_int(usage.get("cache_creation_input_tokens", 0))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cache_tokens": cache_tokens,
    }

def _merge_token_usage(current: dict[str, int], usage: dict[str, int]) -> None:
    current["prompt_tokens"] = max(current["prompt_tokens"], usage.get("prompt_tokens", 0))
    current["completion_tokens"] = max(
        current["completion_tokens"], usage.get("completion_tokens", 0)
    )
    current["total_tokens"] = max(
        current["total_tokens"],
        usage.get("total_tokens", 0),
        current["prompt_tokens"] + current["completion_tokens"],
    )
    current["cache_tokens"] = max(current["cache_tokens"], usage.get("cache_tokens", 0))

def _ensure_openai_stream_usage(provider_request: dict[str, Any], upstream_api_type: str) -> None:
    if upstream_api_type != "openai" or provider_request.get("stream") is not True:
        return

    stream_options = provider_request.get("stream_options")
    if isinstance(stream_options, dict):
        stream_options["include_usage"] = True
        provider_request["stream_options"] = stream_options
        return

    provider_request["stream_options"] = {"include_usage": True}

async def _safe_increment_token_usage(
    api_key_id: str | None,
    token_count: int,
    trace_id: str,
) -> None:
    if not api_key_id or token_count <= 0:
        return
    try:
        await increment_token_usage(api_key_id, token_count)
    except Exception as e:
        logger.exception(
            "Failed to increment API key token usage",
            extra={"trace_id": trace_id, "api_key_id": api_key_id, "token_count": token_count, "error": str(e)[:200]},
        )

def _sse_payloads(chunk_data: str) -> list[dict[str, Any]]:
    payloads = []
    for event in chunk_data.strip().split("\n\n"):
        data_lines = []
        for line in event.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads

def extract_stream_token_usage(chunk_data: str) -> dict[str, int]:
    token_usage = _empty_token_usage()
    for payload in _sse_payloads(chunk_data):
        candidates = [payload]
        for key in ("response", "message"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)

        for candidate in candidates:
            _merge_token_usage(token_usage, extract_token_usage(candidate))
    return token_usage

def _extract_stream_output_text(converted: str) -> str:
    if not settings.log_content:
        return ""
    parts = []
    for payload in _sse_payloads(converted):
        kind = payload.get("type", "")
        choices = payload.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            if delta.get("reasoning_content"):
                parts.append(f"<thinking>{delta['reasoning_content']}</thinking>")
            if delta.get("content"):
                parts.append(str(delta["content"]))
        elif kind == "response.output_text.delta":
            parts.append(str(payload.get("delta", "")))
        elif kind in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            parts.append(f"<thinking>{payload.get('delta', '')}</thinking>")
        elif kind == "content_block_delta":
            delta = payload.get("delta") or {}
            if delta.get("type") == "text_delta":
                parts.append(delta.get("text", ""))
            elif delta.get("type") == "thinking_delta":
                parts.append(f"<thinking>{delta.get('thinking', '')}</thinking>")
    return "".join(parts)

_MAX_LOG_TEXT_LENGTH = 50000

def _truncate(text: str, max_len: int = _MAX_LOG_TEXT_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"...<truncated {len(text) - max_len} chars>"

def _extract_input_content(request_body: dict[str, Any]) -> str:
    if not settings.log_content:
        return ""

    messages = request_body.get("messages")
    if isinstance(messages, list):
        parts = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, str):
                parts.append(f"[{role}] {content}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text", "")
                        if text:
                            parts.append(f"[{role}] {text}")
        return _truncate("\n".join(parts))

    input_val = request_body.get("input")
    if isinstance(input_val, str):
        return _truncate(input_val)
    if isinstance(input_val, list):
        parts = []
        for item in input_val:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text", item.get("content", ""))
                if isinstance(text, str):
                    parts.append(text)
        return _truncate("\n".join(parts))

    return ""

def _extract_output_content(response_data: Any) -> str:
    if not settings.log_content:
        return ""

    if not isinstance(response_data, dict):
        return ""

    choices = response_data.get("choices")
    if isinstance(choices, list):
        parts = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message", {})
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if content:
                    parts.append(str(content))
                reasoning = msg.get("reasoning_content", "")
                if reasoning:
                    parts.append(f"<thinking>{reasoning}</thinking>")
        if parts:
            return _truncate("\n".join(parts))

    content = response_data.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type", "")
                text = block.get("text", "")
                if block_type == "thinking" and text:
                    parts.append(f"<thinking>{text}</thinking>")
                elif block_type == "text" and text:
                    parts.append(text)
        if parts:
            return _truncate("\n".join(parts))
    elif isinstance(content, str):
        return _truncate(content)

    output = response_data.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        parts.append(part.get("text", ""))
            elif item.get("type") == "reasoning":
                for summary in item.get("summary", []):
                    if isinstance(summary, dict) and summary.get("type") == "summary_text":
                        parts.append(f"<thinking>{summary.get('text', '')}</thinking>")
        if parts:
            return _truncate("\n".join(parts))

    output_text = response_data.get("output_text", "")
    if output_text:
        return _truncate(str(output_text))

    return ""

def _serialize_body_for_log(data: Any) -> str:
    if not settings.log_body:
        return ""
    if data is None:
        return ""
    if isinstance(data, str):
        return _truncate(data)
    try:
        return _truncate(json.dumps(data, ensure_ascii=False, default=str))
    except Exception:
        return _truncate(str(data))

def _api_key_log_context(api_key_info: dict[str, Any] | None) -> ApiKeyLogContext:
    if not api_key_info:
        return {"from_apikey": "", "from_apikey_name": ""}

    from_apikey = str(api_key_info.get("id") or "")
    from_apikey_name = str(api_key_info.get("name") or "")
    if not from_apikey and api_key_info.get("key_hash") == "admin_playground":
        from_apikey = "admin_playground"
        from_apikey_name = from_apikey_name or "Admin Playground"

    return {
        "from_apikey": from_apikey,
        "from_apikey_name": from_apikey_name,
    }

def _request_log_context(
    trace_id: str,
    api_key_hash: str,
    api_type: str,
    model: str,
    start_time: float,
    status_code: int,
    error_message: str = "",
    channel_id: str = "",
    channel_name: str = "",
    upstream_url: str = "",
    thinking_effort: str = "none",
    token_usage: dict[str, int] | None = None,
    request_body: str = "",
    response_body: str = "",
    input_content: str = "",
    output_content: str = "",
    from_apikey: str = "",
    from_apikey_name: str = "",
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "api_key_hash": api_key_hash,
        "from_apikey": from_apikey,
        "from_apikey_name": from_apikey_name,
        "api_type": api_type,
        "model": model,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "upstream_url": upstream_url,
        "latency_ms": (time.time() - start_time) * 1000,
        "status_code": status_code,
        "error_message": error_message,
        "thinking_effort": thinking_effort or "none",
        **(token_usage or _empty_token_usage()),
        "request_body": request_body,
        "response_body": response_body,
        "input_content": input_content,
        "output_content": output_content,
    }

def _finish_request_log(
    context: dict[str, Any],
    start_time: float,
    **updates: Any,
) -> None:
    context.update(updates)
    context["latency_ms"] = (time.time() - start_time) * 1000

def _add_request_log_task(background_tasks: BackgroundTasks, context: dict[str, Any]) -> None:
    background_tasks.add_task(plugin_engine.execute_hook, "post_send", context=context)

def _model_default_thinking_applies(model_config: Any | None, request_body: dict[str, Any]) -> bool:
    if not model_config or not getattr(model_config, "supports_thinking", False):
        return False
    effort = str(getattr(model_config, "default_thinking_effort", "none") or "none").strip().lower()
    return effort != "none" and get_effective_thinking_effort(request_body) == "none"

def _apply_claude_default_mode_override(provider_request: dict[str, Any], model_config: Any | None) -> None:
    if not model_config or not getattr(model_config, "supports_thinking", False):
        return

    effort = str(getattr(model_config, "default_thinking_effort", "none") or "none").strip().lower()
    if effort == "none":
        return

    mode = str(getattr(model_config, "claude_thinking_mode", "adaptive") or "adaptive").strip().lower()
    if mode == "disabled":
        provider_request.pop("thinking", None)
        output_config = provider_request.get("output_config")
        if isinstance(output_config, dict):
            output_config.pop("effort", None)
            if not output_config:
                provider_request.pop("output_config", None)
        return

    if mode == "enabled":
        budget_map = {"low": 1024, "medium": 2048, "high": 4096}
        provider_request["thinking"] = {
            "type": "enabled",
            "budget_tokens": budget_map.get(effort, 2048),
            "display": "summarized",
        }
        provider_request.pop("output_config", None)

def create_error_response(status_code: int, message: str, api_type: str) -> JSONResponse:
    return api_error_response(
        status_code=status_code,
        message=message,
        api_type=api_type,
        code=str(status_code) if api_type != "claude" else None,
        request_id=get_trace_id(),
    )

def create_error_body(
    status_code: int,
    message: str,
    api_type: str,
    detail: Any = None,
) -> dict[str, Any]:
    return api_error_body(
        status_code=status_code,
        message=message,
        api_type=api_type,
        error_type=api_error_type(status_code, api_type, detail),
        code=str(status_code) if api_type != "claude" else None,
        request_id=get_trace_id(),
    )

def stream_error_event(status_code: int, message: str, api_type: str, detail: Any = None, *, sequence_number: int = 0) -> str:
    body = create_error_body(status_code, message, api_type, detail)
    payload = json.dumps(body, ensure_ascii=False)
    if api_type == "responses":
        return "event: error\ndata: " + json.dumps({
            "type": "error", "code": str(status_code), "message": message,
            "param": None, "sequence_number": sequence_number,
        }, ensure_ascii=False) + "\n\n"
    if api_type == "claude":
        return f"event: error\ndata: {payload}\n\n"
    return f"data: {payload}\n\n"

async def handle_gateway_request(
    request: Request,
    background_tasks: BackgroundTasks,
    api_type: str,
):
    trace_id = get_trace_id()
    start_time = time.time()
    api_key_info = getattr(request.state, "api_key_info", None)
    api_key_hash = api_key_info["key_hash"] if api_key_info else ""
    api_key_id = api_key_info["id"] if api_key_info else None
    api_key_log_context = _api_key_log_context(api_key_info)

    try:
        parsed_body = await request.json()
    except Exception:
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, "", start_time, 400,
                "Invalid JSON request body",
                **api_key_log_context,
            ),
        )
        return create_error_response(400, "Invalid JSON request body", api_type)
    if not isinstance(parsed_body, dict):
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, "", start_time, 400,
                "JSON request body must be an object",
                **api_key_log_context,
            ),
        )
        return create_error_response(400, "JSON request body must be an object", api_type)

    request_body: dict[str, Any] = parsed_body

    model_name = request_body.get("model", "")
    if not isinstance(model_name, str) or not model_name:
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, "", start_time, 400,
                "model is required",
                **api_key_log_context,
            ),
        )
        return create_error_response(400, "model is required", api_type)

    if api_key_info and not check_model_access(api_key_info, model_name):
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, model_name, start_time, 403,
                f"API key does not have access to model '{model_name}'",
                **api_key_log_context,
            ),
        )
        return create_error_response(403, f"This API key does not have access to model '{model_name}'", api_type)

    allowed, rate_limit_reason = await check_rate_limit(api_key_hash, model_name)
    if not allowed:
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, model_name, start_time, 429,
                f"Rate limit exceeded: {rate_limit_reason}",
                **api_key_log_context,
            ),
        )
        return create_error_response(429, f"Rate limit exceeded: {rate_limit_reason}", api_type)

    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.model_config import ModelConfig

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.name == model_name)
        )
        model_config = result.scalar_one_or_none()

    request_body = apply_default_thinking(request_body, api_type, model_config)
    thinking_effort = get_effective_thinking_effort(request_body)

    if request_body.get("stream", False):
        log_context = _request_log_context(
            trace_id, api_key_hash, api_type, model_name, start_time, 499,
            "Stream did not complete",
            thinking_effort=thinking_effort,
            request_body=_serialize_body_for_log(request_body),
            input_content=_extract_input_content(request_body),
            **api_key_log_context,
        )
        return StreamingResponse(
            stream_gateway_request(
                request_body, api_type, trace_id, api_key_hash, start_time, log_context, api_key_id
            ),
            media_type="text/event-stream",
            headers={"x-request-id": trace_id, "x-trace-id": trace_id},
        )

    request_body = await plugin_engine.execute_hook(
        "pre_route", request_body=request_body, api_type=api_type,
        context={"trace_id": trace_id, "api_key_hash": api_key_hash}
    )
    if not isinstance(request_body, dict):
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, model_name, start_time, 500,
                "pre_route hook returned invalid request body",
                thinking_effort=thinking_effort,
                **api_key_log_context,
            ),
        )
        return create_error_response(500, "pre_route hook returned invalid request body", api_type)
    model_name = request_body.get("model", model_name)
    thinking_effort = get_effective_thinking_effort(request_body)

    channels, model_config = await route_request(model_name, api_type, request_body)

    channels = await plugin_engine.execute_hook(
        "on_channel_select", channels=channels,
        context={"trace_id": trace_id, "api_type": api_type, "model": model_name}
    )

    try:
        channel, response, status_code, channel_url = await _call_upstream_channels(
            channels, request_body, api_type, trace_id, api_key_hash, model_config
        )
    except NoRetryError as e:
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, model_name, start_time,
                e.status_code, extract_error_message(e.error_body),
                thinking_effort=thinking_effort,
                **api_key_log_context,
            ),
        )
        return JSONResponse(content=e.error_body, status_code=e.status_code)
    except UpstreamAPIError as e:
        _add_request_log_task(
            background_tasks,
            _request_log_context(
                trace_id, api_key_hash, api_type, model_name, start_time,
                e.status_code, extract_error_message(e.error_body),
                thinking_effort=thinking_effort,
                **api_key_log_context,
            ),
        )
        return JSONResponse(content=e.error_body, status_code=e.status_code)

    token_usage = extract_token_usage(response)
    _add_request_log_task(
        background_tasks,
        _request_log_context(
            trace_id, api_key_hash, api_type, model_name, start_time,
            status_code, channel_id=channel.channel_id or "inline",
            channel_name=channel.name, upstream_url=channel_url,
            token_usage=token_usage,
            thinking_effort=thinking_effort,
            request_body=_serialize_body_for_log(request_body),
            response_body=_serialize_body_for_log(response),
            input_content=_extract_input_content(request_body),
            output_content=_extract_output_content(response),
            **api_key_log_context,
        ),
    )

    await _safe_increment_token_usage(
        api_key_id, token_usage.get("total_tokens", 0), trace_id
    )

    return JSONResponse(content=response, status_code=status_code)


async def _call_upstream_channels(
    channels: list[ChannelInfo],
    request_body: dict[str, Any],
    api_type: str,
    trace_id: str,
    api_key_hash: str,
    model_config: Any | None,
) -> tuple[ChannelInfo, dict[str, Any], int, str]:
    last_error = None
    last_status_code = 503

    for channel in channels:
        async with request_permit(channel.circuit_key, channel.timeout or settings.default_channel_timeout) as permit:
            if permit is None:
                continue
            try:
                response, status_code, channel_url = await try_channel(
                    channel, request_body, api_type, trace_id, api_key_hash, model_config
                )
            except NoRetryError:
                raise
            except Exception as e:
                last_error = str(e)
                last_status_code = getattr(e, "status_code", 502)
                await record_failure(channel.circuit_key, permit)
                error_decision = await plugin_engine.execute_hook(
                    "on_error", error=e, channel_info=channel,
                    context={"trace_id": trace_id, "api_type": api_type, "model": request_body.get("model", "")}
                )
                if error_decision and not error_decision.get("retry", True):
                    break
                logger.warning("Channel failed, trying next", extra={"trace_id": trace_id, "channel": channel.name})
            else:
                # Circuit bookkeeping must not replay a successful model call.
                try:
                    await record_success(channel.circuit_key, permit)
                except Exception:
                    logger.exception("Failed to record circuit success", extra={"trace_id": trace_id})
                return channel, response, status_code, channel_url

    raise UpstreamAPIError(
        status_code=last_status_code,
        error_body=create_error_body(
            last_status_code,
            last_error or "All upstream channels failed",
            api_type,
            {},
        ),
    )

async def try_channel(
    channel: ChannelInfo,
    request_body: dict[str, Any],
    api_type: str,
    trace_id: str,
    api_key_hash: str,
    model_config: Any | None = None,
) -> tuple[dict[str, Any], int, str]:
    adapter, provider_request, headers, url, upstream_api_type = await build_upstream_request(
        channel, request_body, api_type, trace_id, api_key_hash, model_config
    )
    timeout = channel.timeout or settings.default_channel_timeout

    log_upstream_request(logger, "POST", url, provider_request, trace_id, channel.name)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=provider_request, headers=headers)
    log_upstream_response(logger, "POST", url, resp.status_code, resp.text, trace_id, channel.name)

    status_code = resp.status_code

    if status_code >= 400:
        error_body = {}
        try:
            error_body = resp.json()
        except Exception:
            error_body = {"error": {"message": resp.text[:500]}}

        mapped_error = create_error_body(
            status_code,
            extract_error_message(error_body),
            api_type,
            error_body,
        )
        if status_code == 400:
            raise NoRetryError(status_code=status_code, error_body=mapped_error)
        raise UpstreamAPIError(status_code=status_code, error_body=mapped_error)

    response_body = resp.json()

    provider_response = adapter.convert_response(
        response_body, upstream_api_type, provider_request
    )
    final_response = transform_response_body(
        provider_response, upstream_api_type, api_type, request_body
    )

    final_response = await plugin_engine.execute_hook(
        "post_response", response=final_response, api_type=api_type,
        context={"trace_id": trace_id, "api_key_hash": api_key_hash,
                 "model": request_body.get("model", "")}
    )
    if not isinstance(final_response, dict):
        raise HTTPException(status_code=500, detail="post_response hook returned invalid response")

    return final_response, status_code, url

async def build_upstream_request(
    channel: ChannelInfo,
    request_body: dict[str, Any],
    api_type: str,
    trace_id: str,
    api_key_hash: str,
    model_config: Any | None = None,
):
    adapter = get_adapter(channel.provider)

    adapted_body = await plugin_engine.execute_hook(
        "pre_request", request_body=request_body, channel_info=channel,
        api_type=api_type,
        context={"trace_id": trace_id, "api_key_hash": api_key_hash}
    )
    if not isinstance(adapted_body, dict):
        raise HTTPException(status_code=500, detail="pre_request hook returned invalid request body")

    upstream_body: dict[str, Any] = dict(adapted_body)
    if channel.upstream_model_id:
        upstream_body["model"] = channel.upstream_model_id

    upstream_api_type = resolve_channel_api_type(channel, api_type, upstream_body)
    try:
        normalized_body = transform_request_body(upstream_body, api_type, upstream_api_type)
    except ValueError as exc:
        raise NoRetryError(400, create_error_body(400, str(exc), api_type)) from exc
    provider_request = adapter.convert_request(normalized_body, upstream_api_type)
    if upstream_api_type == "claude" and _model_default_thinking_applies(model_config, request_body):
        _apply_claude_default_mode_override(provider_request, model_config)
    _ensure_openai_stream_usage(provider_request, upstream_api_type)
    headers = merge_custom_headers(adapter.get_headers(channel.api_key), channel.custom_headers)
    url = adapter.get_url(channel.base_url, upstream_api_type)

    return adapter, provider_request, headers, url, upstream_api_type

async def iter_sse_events(
    resp: httpx.Response,
    url: str,
    trace_id: str,
    channel_name: str,
):
    event_lines: list[str] = []
    async for line in resp.aiter_lines():
        if line == "":
            if event_lines:
                event = "\n".join(event_lines) + "\n\n"
                log_upstream_response(logger, "POST", url, resp.status_code, event, trace_id, channel_name)
                yield event
                event_lines = []
            continue
        event_lines.append(line)

    if event_lines:
        event = "\n".join(event_lines) + "\n\n"
        log_upstream_response(logger, "POST", url, resp.status_code, event, trace_id, channel_name)
        yield event

async def stream_gateway_request(
    request_body: dict[str, Any],
    api_type: str,
    trace_id: str,
    api_key_hash: str,
    start_time: float,
    log_context: dict[str, Any],
    api_key_id: str | None = None,
):
    total_usage = _empty_token_usage()
    output_text = ""
    status_code = 499
    error_message = "Client disconnected before the stream completed"
    try:
        request_body = await plugin_engine.execute_hook(
            "pre_route", request_body=request_body, api_type=api_type,
            context={"trace_id": trace_id, "api_key_hash": api_key_hash},
        )
        if not isinstance(request_body, dict):
            raise StreamProtocolError("pre_route hook returned invalid request body", 500)
        model_name = request_body.get("model", "")
        channels, model_config = await route_request(model_name, api_type, request_body)
        request_body = apply_default_thinking(request_body, api_type, model_config)
        log_context.update(
            model=model_name, request_body=_serialize_body_for_log(request_body),
            input_content=_extract_input_content(request_body),
            thinking_effort=get_effective_thinking_effort(request_body),
        )
        channels = await plugin_engine.execute_hook(
            "on_channel_select", channels=channels,
            context={"trace_id": trace_id, "api_type": api_type, "model": model_name},
        )
        status_code = 503
        error_message = f"No available channels for model {model_name}"
        for channel in channels or []:
            token_usage = _empty_token_usage()
            state: StreamState | None = None
            data_sent = False
            completed = False
            failed = False
            timeout = channel.timeout or settings.default_channel_timeout
            async with request_permit(channel.circuit_key, timeout) as permit:
                if permit is None:
                    continue
                log_context.update(channel_id=channel.channel_id or "inline", channel_name=channel.name)
                status_code, error_message = 499, "Client disconnected before the stream completed"
                try:
                    adapter, provider_request, headers, url, upstream_api_type = await build_upstream_request(
                        channel, request_body, api_type, trace_id, api_key_hash, model_config,
                    )
                    log_context["upstream_url"] = url
                    state = StreamState(upstream_api_type, api_type, model_name)
                    log_upstream_request(logger, "POST", url, provider_request, trace_id, channel.name)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        async with client.stream("POST", url, json=provider_request, headers=headers) as resp:
                            if not 200 <= resp.status_code < 300:
                                raw = await resp.aread()
                                try:
                                    detail = json.loads(raw)
                                except ValueError:
                                    detail = {"error": {"message": raw.decode(errors="replace")[:500]}}
                                upstream_status = resp.status_code if resp.status_code >= 400 else 502
                                raise UpstreamAPIError(upstream_status, create_error_body(
                                    upstream_status, extract_error_message(detail), api_type, detail,
                                ))
                            async for event in iter_sse_events(resp, url, trace_id, channel.name):
                                provider_chunk = await adapter.convert_stream_chunk(event, upstream_api_type)
                                if not provider_chunk:
                                    continue
                                _merge_token_usage(token_usage, extract_stream_token_usage(provider_chunk))
                                converted = transform_stream_chunk(provider_chunk, upstream_api_type, api_type, state)
                                if state.finished:
                                    completed = True
                                    status_code, error_message = 200, ""
                                if converted:
                                    if settings.log_content and len(output_text) < _MAX_LOG_TEXT_LENGTH:
                                        output_text += _extract_stream_output_text(converted)[:_MAX_LOG_TEXT_LENGTH - len(output_text)]
                                    # Set before yielding: generator close/cancellation can
                                    # occur while suspended at this exact yield.
                                    data_sent = True
                                    yield converted
                                if state.finished:
                                    break
                            if not completed:
                                raise StreamProtocolError("Upstream stream ended before its terminal event")
                    return
                except (asyncio.CancelledError, GeneratorExit):
                    raise
                except Exception as exc:
                    failed = True
                    status_code = getattr(exc, "status_code", 502)
                    error_message = extract_error_message(exc.error_body) if isinstance(exc, (NoRetryError, UpstreamAPIError)) else str(exc)
                    if data_sent or status_code == 400:
                        yield stream_error_event(status_code, error_message, api_type,
                                                 sequence_number=state.sequence if state else 0)
                        return
                    logger.warning("Stream channel failed, trying next", extra={"trace_id": trace_id, "channel": channel.name})
                finally:
                    for key in total_usage:
                        total_usage[key] += token_usage[key]
                    with anyio.CancelScope(shield=True):
                        try:
                            if completed:
                                await record_success(channel.circuit_key, permit)
                            elif failed and status_code != 400:
                                await record_failure(channel.circuit_key, permit)
                        except Exception:
                            logger.exception("Failed to update stream circuit state", extra={"trace_id": trace_id})
        yield stream_error_event(status_code, error_message, api_type)
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception as exc:
        status_code = getattr(exc, "status_code", 500)
        error_message = str(exc)
        yield stream_error_event(status_code, error_message, api_type)
    finally:
        # Starlette cancels the producer when the client disconnects. Shield
        # bookkeeping so known usage and the final log are still persisted.
        with anyio.CancelScope(shield=True):
            _finish_request_log(
                log_context, start_time, status_code=status_code, error_message=error_message,
                output_content=output_text, response_body=_serialize_body_for_log("<streaming>"),
                **total_usage,
            )
            await _safe_increment_token_usage(api_key_id, total_usage["total_tokens"], trace_id)
            await plugin_engine.execute_hook("post_send", context=log_context)
