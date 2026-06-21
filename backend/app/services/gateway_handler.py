import json
import time
from typing import Any, TypedDict

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
from app.services.circuit_breaker import record_success, record_failure
from app.services.rate_limiter import check_rate_limit
from app.adapters.generic_adapter import get_adapter
from app.adapters.base_adapter import merge_custom_headers
from app.plugins.plugin_engine import plugin_engine
from app.services.request_transformer import (
    ClaudeStreamState,
    apply_default_thinking,
    get_effective_thinking_effort,
    is_stream_done_chunk,
    resolve_channel_api_type,
    stream_done_marker,
    transform_request_body,
    transform_response_body,
    transform_stream_chunk,
)

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
    try:
        for line in converted.strip().split("\n"):
            if line.startswith("data:"):
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                payload = json.loads(data)
                if not isinstance(payload, dict):
                    continue
                ptype = payload.get("type", "")

                choices = payload.get("choices")
                if isinstance(choices, list) and choices:
                    delta = choices[0].get("delta", {}) if isinstance(choices[0], dict) else {}
                    content = delta.get("content", "")
                    reasoning = delta.get("reasoning_content", "")
                    if content:
                        return content
                    if reasoning:
                        return f"<thinking>{reasoning}</thinking>"

                if ptype == "response.output_text.delta":
                    return str(payload.get("delta", ""))
                if ptype == "response.reasoning_summary_text.delta":
                    return f"<thinking>{payload.get('delta', '')}</thinking>"

                if ptype == "content_block_delta":
                    delta = payload.get("delta", {})
                    delta_type = delta.get("type", "")
                    if delta_type == "text_delta":
                        return delta.get("text", "")
                    if delta_type == "thinking_delta":
                        return f"<thinking>{delta.get('thinking', '')}</thinking>"
    except Exception:
        pass
    return ""

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

def stream_error_event(status_code: int, message: str, api_type: str, detail: Any = None) -> str:
    body = create_error_body(status_code, message, api_type, detail)
    payload = json.dumps(body, ensure_ascii=False)
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
        _add_request_log_task(background_tasks, log_context)
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
        try:
            response, status_code, channel_url = await try_channel(
                channel, request_body, api_type, trace_id, api_key_hash, model_config
            )

            if channel.channel_id:
                await record_success(channel.channel_id)

            return channel, response, status_code, channel_url
        except NoRetryError:
            raise
        except Exception as e:
            last_error = str(e)
            last_status_code = getattr(e, "status_code", 500)

            if channel.channel_id:
                await record_failure(channel.channel_id)

            error_decision = await plugin_engine.execute_hook(
                "on_error", error=e, channel_info=channel,
                context={"trace_id": trace_id, "api_type": api_type, "model": request_body.get("model", "")}
            )
            if error_decision and not error_decision.get("retry", True):
                break

            logger.warning(
                f"Channel {channel.name} failed, trying next",
                extra={"trace_id": trace_id, "error": str(e)[:200]}
            )

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
    normalized_body = transform_request_body(upstream_body, api_type, upstream_api_type)
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
    model_name = request_body.get("model", "")
    last_token_usage = _empty_token_usage()
    last_error = "All channels failed"
    last_status_code = 503
    stream_output_parts: list[str] = []

    request_body = await plugin_engine.execute_hook(
        "pre_route", request_body=request_body, api_type=api_type,
        context={"trace_id": trace_id, "api_key_hash": api_key_hash}
    )
    if not isinstance(request_body, dict):
        _finish_request_log(
            log_context,
            start_time,
            status_code=500,
            error_message="pre_route hook returned invalid request body",
        )
        yield stream_error_event(500, "pre_route hook returned invalid request body", api_type)
        yield stream_done_marker(api_type)
        return
    model_name = request_body.get("model", model_name)

    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.model_config import ModelConfig

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.name == model_name)
        )
        model_config = result.scalar_one_or_none()

    request_body = apply_default_thinking(request_body, api_type, model_config)
    _finish_request_log(
        log_context,
        start_time,
        model=model_name,
        request_body=_serialize_body_for_log(request_body),
        input_content=_extract_input_content(request_body),
        thinking_effort=get_effective_thinking_effort(request_body),
    )

    channels, _model_config = await route_request(model_name, api_type, request_body)
    channels = await plugin_engine.execute_hook(
        "on_channel_select", channels=channels,
        context={"trace_id": trace_id, "api_type": api_type, "model": model_name}
    )
    if not channels:
        last_error = f"No available channels for model {model_name}"
        _finish_request_log(
            log_context,
            start_time,
            status_code=503,
            error_message=last_error,
        )
        yield stream_error_event(503, last_error, api_type)
        yield stream_done_marker(api_type)
        return

    for channel in channels:
        token_usage = _empty_token_usage()
        data_sent = False
        try:
            adapter, provider_request, headers, url, upstream_api_type = await build_upstream_request(
                channel, request_body, api_type, trace_id, api_key_hash, model_config
            )
            claude_state = ClaudeStreamState() if (api_type == "claude" and upstream_api_type != api_type) else None
            timeout = channel.timeout or settings.default_channel_timeout

            log_upstream_request(logger, "POST", url, provider_request, trace_id, channel.name)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=provider_request, headers=headers) as resp:
                    log_upstream_response(logger, "POST", url, resp.status_code, "<streaming response>", trace_id, channel.name)
                    last_status_code = resp.status_code
                    if resp.status_code >= 500:
                        last_error = f"Upstream returned HTTP {resp.status_code}"
                        last_token_usage = token_usage
                        if channel.channel_id:
                            await record_failure(channel.channel_id)
                        continue

                    if resp.status_code >= 400:
                        error_text = await resp.aread()
                        log_upstream_response(logger, "POST", url, resp.status_code, error_text, trace_id, channel.name)
                        error_message = error_text.decode(errors="replace")[:500]
                        if resp.status_code == 400:
                            _finish_request_log(
                                log_context,
                                start_time,
                                status_code=400,
                                error_message=error_message,
                                channel_id=channel.channel_id or "inline",
                                channel_name=channel.name,
                                upstream_url=url,
                            )
                            yield stream_error_event(400, error_message, api_type)
                            yield stream_done_marker(api_type)
                            return
                        if channel.channel_id:
                            await record_failure(channel.channel_id)
                        last_error = f"Upstream returned HTTP {resp.status_code}: {error_message}"
                        last_status_code = resp.status_code
                        last_token_usage = token_usage
                        continue

                    received_done = False
                    async for event in iter_sse_events(resp, url, trace_id, channel.name):
                        provider_chunk = await adapter.convert_stream_chunk(event, upstream_api_type)
                        if provider_chunk:
                            _merge_token_usage(token_usage, extract_stream_token_usage(provider_chunk))
                            if is_stream_done_chunk(provider_chunk):
                                received_done = True
                            converted = transform_stream_chunk(provider_chunk, upstream_api_type, api_type, claude_state)
                            if converted:
                                stream_output_parts.append(_extract_stream_output_text(converted))
                                yield converted
                                data_sent = True

                    if not received_done:
                        yield stream_done_marker(api_type)

            if channel.channel_id:
                await record_success(channel.channel_id)
            _finish_request_log(
                log_context,
                start_time,
                status_code=200,
                error_message="",
                channel_id=channel.channel_id or "inline",
                channel_name=channel.name,
                upstream_url=url,
                response_body=_serialize_body_for_log("<streaming>"),
                output_content=_truncate("".join(stream_output_parts)),
                **token_usage,
            )
            await _safe_increment_token_usage(
                api_key_id, token_usage.get("total_tokens", 0), trace_id
            )
            return

        except Exception as e:
            last_token_usage = token_usage
            last_error = str(e)
            last_status_code = getattr(e, "status_code", 500)

            if data_sent:
                if channel.channel_id:
                    await record_failure(channel.channel_id)
                logger.error(
                    f"Stream channel {channel.name} failed after data was sent, cannot fallback",
                    extra={"trace_id": trace_id, "error": str(e)[:200]}
                )
                _finish_request_log(
                    log_context,
                    start_time,
                    status_code=last_status_code,
                    error_message=last_error,
                    channel_id=channel.channel_id or "inline",
                    channel_name=channel.name,
                    **last_token_usage,
                )
                yield stream_error_event(last_status_code, f"Stream interrupted: {last_error}", api_type)
                yield stream_done_marker(api_type)
                return

            if last_status_code == 400:
                _finish_request_log(
                    log_context,
                    start_time,
                    status_code=400,
                    error_message=last_error,
                    channel_id=channel.channel_id or "inline",
                    channel_name=channel.name,
                )
                yield stream_error_event(400, last_error, api_type)
                yield stream_done_marker(api_type)
                return

            if channel.channel_id:
                await record_failure(channel.channel_id)
            logger.warning(f"Stream channel {channel.name} failed: {e}")
            continue

    _finish_request_log(
        log_context,
        start_time,
        status_code=last_status_code,
        error_message=last_error,
        **last_token_usage,
    )
    if api_type in ("openai", "responses"):
        yield stream_error_event(last_status_code, last_error, api_type)
        yield stream_done_marker(api_type)
    else:
        yield stream_error_event(last_status_code, last_error, api_type)
        yield stream_done_marker(api_type)
