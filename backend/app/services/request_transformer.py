import json
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.routing_engine import ChannelInfo

from app.services.stream_transformer import (
    StreamState, make_compat_thinking_signature, stop_reason,
)

API_TYPE_ALIASES = {
    "chat": "openai",
    "chat_completions": "openai",
    "openai_chat": "openai",
    "openai": "openai",
    "auto": "auto",
    "responses": "responses",
    "openai_responses": "responses",
    "claude": "claude",
    "anthropic": "claude",
    "messages": "claude",
}

OPENAI_CHAT_FIELDS = {
    "model", "messages", "max_tokens", "max_completion_tokens", "temperature",
    "top_p", "n", "stream", "stop", "presence_penalty", "frequency_penalty",
    "logit_bias", "user", "tools", "tool_choice", "parallel_tool_calls",
    "response_format", "seed", "logprobs", "top_logprobs", "stream_options",
    "modalities", "audio", "prediction", "reasoning_effort", "service_tier",
    "metadata", "store",
}

OPENAI_RESPONSES_FIELDS = {
    "model", "input", "include", "instructions", "max_output_tokens", "metadata",
    "parallel_tool_calls", "previous_response_id", "reasoning", "service_tier",
    "store", "stream", "temperature", "text", "tool_choice", "tools", "top_p",
    "truncation", "user",
}

CLAUDE_FIELDS = {
    "model", "messages", "max_tokens", "system", "metadata", "stop_sequences",
    "stream", "temperature", "thinking", "output_config", "tool_choice", "tools", "top_k", "top_p",
}

DEFAULT_THINKING_EFFORTS = {"none", "low", "medium", "high"}
CLAUDE_MANUAL_THINKING_BUDGETS = {"low": 1024, "medium": 2048, "high": 4096}

def normalize_api_type(api_type: str | None, provider: str = "") -> str:
    normalized = API_TYPE_ALIASES.get((api_type or "").strip().lower())
    if normalized:
        return normalized
    return default_api_type_for_provider(provider)

def default_api_type_for_provider(provider: str) -> str:
    if provider == "anthropic":
        return "claude"
    return "openai"

def resolve_channel_api_type(
    channel: "ChannelInfo",
    incoming_api_type: str,
    request_body: dict[str, Any] | None = None,
) -> str:
    configured = getattr(channel, "api_type", "") or ""
    inline_config = getattr(channel, "inline_config", None) or {}
    if not configured and isinstance(inline_config, dict):
        configured = (
            inline_config.get("api_type")
            or inline_config.get("upstream_api_type")
            or inline_config.get("protocol")
            or ""
        )

    configured_api_type = configured or incoming_api_type
    normalized = normalize_channel_api_type(str(configured_api_type), channel.provider)

    if normalized == "auto":
        if channel.provider == "anthropic":
            return "claude"
        if request_uses_openai_reasoning(request_body or {}) and _provider_supports_responses(channel.provider):
            return "responses"
        return "openai"

    return normalized

def normalize_channel_api_type(api_type: str | None, provider: str = "") -> str:
    normalized = normalize_api_type(api_type, provider)
    if provider == "anthropic":
        return "claude"
    if provider in ("openai", "azure", "google") and normalized == "claude":
        return "openai"
    return normalized

def request_uses_openai_reasoning(request_body: dict[str, Any]) -> bool:
    reasoning = request_body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        return True
    if request_body.get("reasoning_effort"):
        return True
    thinking = request_body.get("thinking")
    if isinstance(thinking, dict) and (
        thinking.get("effort") or thinking.get("budget_tokens") or thinking.get("type") == "adaptive"
    ):
        return True
    if isinstance(thinking, str) and thinking:
        return True
    return False

def get_effective_thinking_effort(request_body: dict[str, Any]) -> str:
    reasoning = request_body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        return str(reasoning["effort"])
    if request_body.get("reasoning_effort"):
        return str(request_body["reasoning_effort"])

    output_config = request_body.get("output_config")
    if isinstance(output_config, dict) and output_config.get("effort"):
        return str(output_config["effort"])

    thinking = request_body.get("thinking")
    if isinstance(thinking, str) and thinking:
        return str(thinking)
    if isinstance(thinking, dict):
        effort = thinking.get("effort")
        if effort:
            return str(effort)
        budget_effort = _thinking_to_reasoning_effort(thinking)
        if budget_effort:
            return budget_effort

    return "none"

def apply_default_thinking(
    request_body: dict[str, Any],
    api_type: str,
    model_config: Any | None,
) -> dict[str, Any]:
    if not model_config or not getattr(model_config, "supports_thinking", False):
        return request_body

    effort = _normalize_default_thinking_effort(getattr(model_config, "default_thinking_effort", "none"))
    normalized_api_type = normalize_api_type(api_type)
    if normalized_api_type == "claude":
        result = dict(request_body)
        _apply_default_claude_thinking(result, effort, getattr(model_config, "claude_thinking_mode", "adaptive"))
        return result

    if effort == "none" or _has_client_thinking_config(request_body):
        return request_body

    result = dict(request_body)
    if normalized_api_type == "responses":
        existing_reasoning = result.get("reasoning")
        reasoning: dict[str, Any] = dict(existing_reasoning) if isinstance(existing_reasoning, dict) else {}
        if "effort" not in reasoning:
            reasoning = {**reasoning, "effort": effort}
        result["reasoning"] = reasoning
    else:
        result["reasoning_effort"] = effort

    return result

def _normalize_default_thinking_effort(effort: Any) -> str:
    value = str(effort or "none").strip().lower()
    return value if value in DEFAULT_THINKING_EFFORTS else "none"

def _normalize_claude_thinking_mode(mode: Any) -> str:
    value = str(mode or "adaptive").strip().lower()
    return value if value in {"adaptive", "enabled", "disabled"} else "adaptive"

def _has_client_thinking_config(request_body: dict[str, Any]) -> bool:
    if request_body.get("reasoning_effort"):
        return True
    reasoning = request_body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        return True
    if request_body.get("thinking"):
        return True
    output_config = request_body.get("output_config")
    return isinstance(output_config, dict) and bool(output_config.get("effort"))

def _apply_default_claude_thinking(
    request_body: dict[str, Any],
    effort: str,
    claude_thinking_mode: Any,
) -> None:
    mode = _normalize_claude_thinking_mode(claude_thinking_mode)
    thinking = request_body.get("thinking")
    output_config = request_body.get("output_config")
    if not isinstance(output_config, dict):
        output_config = {}

    if isinstance(thinking, dict):
        if "display" not in thinking:
            request_body["thinking"] = {**thinking, "display": "summarized"}
        if thinking.get("type") == "adaptive" and effort != "none" and "effort" not in output_config:
            output_config["effort"] = effort
            request_body["output_config"] = output_config
        return
    if thinking:
        return

    if effort == "none":
        return
    if mode == "disabled":
        return

    if mode == "enabled":
        request_body["thinking"] = {
            "type": "enabled",
            "budget_tokens": CLAUDE_MANUAL_THINKING_BUDGETS.get(effort, 2048),
            "display": "summarized",
        }
        return

    request_body["thinking"] = {"type": "adaptive", "display": "summarized"}
    if "effort" not in output_config:
        output_config["effort"] = effort
    request_body["output_config"] = output_config

def _provider_supports_responses(provider: str) -> bool:
    return provider in ("openai", "azure", "custom", "google", "cliproxyapi")

def transform_request_body(
    request_body: dict[str, Any],
    source_api_type: str,
    target_api_type: str,
) -> dict[str, Any]:
    source = normalize_api_type(source_api_type)
    target = normalize_api_type(target_api_type)

    if target == "auto":
        target = "responses" if request_uses_openai_reasoning(request_body) else "openai"

    if source != target and request_body.get("n", 1) != 1:
        raise ValueError("Multiple choices cannot be converted between protocols")
    if target == "openai":
        result = _to_openai_chat_request(request_body, source)
    elif target == "responses":
        result = _to_responses_request(request_body, source)
    elif target == "claude":
        result = _to_claude_request(request_body, source)
    else:
        return dict(request_body)
    _convert_tools(result, request_body, source, target)
    return result


def transform_response_body(
    response_body: dict[str, Any],
    source_api_type: str,
    target_api_type: str,
    original_request: dict[str, Any],
) -> dict[str, Any]:
    source = normalize_api_type(source_api_type)
    target = normalize_api_type(target_api_type)

    if target == "auto":
        target = "openai"

    if source == target:
        if target == "claude" and isinstance(response_body.get("content"), list):
            content = [
                {**block, "signature": make_compat_thinking_signature()}
                if block.get("type") == "thinking" and not block.get("signature") else block
                for block in response_body["content"]
            ]
            return {**response_body, "content": content}
        return response_body
    calls = _response_tool_calls(response_body, source)
    if source == "openai":
        choices = response_body.get("choices") or [{}]
        reason = choices[0].get("finish_reason")
    elif source == "claude":
        reason = response_body.get("stop_reason")
    else:
        reason = (response_body.get("incomplete_details") or {}).get("reason")
    if target == "openai":
        result = _to_openai_chat_response(response_body, source, original_request)
        choice = result["choices"][0]
        choice["finish_reason"] = stop_reason(reason, target, bool(calls))
        reasoning = "".join(b["text"] for b in _response_content_blocks(response_body, source) if b["kind"] == "thinking")
        if reasoning:
            choice["message"]["reasoning_content"] = reasoning
        if calls:
            choice["message"]["tool_calls"] = calls
            if not choice["message"]["content"]:
                choice["message"]["content"] = None
    elif target == "responses":
        result = _to_responses_response(response_body, source, original_request)
        if stop_reason(reason, "openai") in ("length", "content_filter"):
            result["status"] = "incomplete"
            result["incomplete_details"] = {"reason": "max_output_tokens" if stop_reason(reason, "openai") == "length" else "content_filter"}
    elif target == "claude":
        result = _to_claude_response(response_body, source, original_request)
        result["stop_reason"] = stop_reason(reason, target, bool(calls))
    else:
        return response_body
    return result


def transform_stream_chunk(
    chunk_data: str,
    source_api_type: str,
    target_api_type: str,
    state: StreamState | None = None,
) -> str | None:
    source = normalize_api_type(source_api_type)
    target = normalize_api_type(target_api_type)
    if target == "auto":
        target = "openai"
    if state is None:
        state = StreamState(source, target)
    state.source, state.target = source, target
    return state.feed(chunk_data)

def _filter_fields(body: dict[str, Any], allowed_fields: set[str]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key in allowed_fields and value is not None}

def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    text_parts.append(text)
        return "".join(text_parts)
    return str(content)

def _responses_content_to_openai(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _content_to_text(content)

    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({"type": "text", "text": str(item)})
            continue

        item_type = item.get("type")
        if item_type in ("input_text", "output_text", "text"):
            text = item.get("text")
            if text:
                parts.append({"type": "text", "text": str(text)})
        elif item_type == "input_image":
            image_url = item.get("image_url") or item.get("url")
            if image_url:
                parts.append({"type": "image_url", "image_url": {"url": image_url}})
        else:
            text = item.get("text") or item.get("content")
            if text:
                parts.append({"type": "text", "text": str(text)})

    return parts or ""

def _to_openai_chat_request(body: dict[str, Any], source_api_type: str) -> dict[str, Any]:
    if source_api_type == "openai" and "messages" in body:
        return _filter_fields(body, OPENAI_CHAT_FIELDS)

    result: dict[str, Any] = {"model": body.get("model", ""), "messages": _messages_as_chat(body, source_api_type)}
    if source_api_type == "claude" and "stop_sequences" in body:
        result["stop"] = body["stop_sequences"]
    if "max_completion_tokens" in body:
        result["max_completion_tokens"] = body["max_completion_tokens"]
    elif "max_tokens" in body:
        result["max_tokens"] = body["max_tokens"]
    elif "max_output_tokens" in body:
        result["max_tokens"] = body["max_output_tokens"]
    if isinstance(body.get("reasoning"), dict) and body["reasoning"].get("effort"):
        result["reasoning_effort"] = body["reasoning"]["effort"]
    _copy_common_openai_params(body, result)
    return _filter_fields(result, OPENAI_CHAT_FIELDS)

def _to_responses_request(body: dict[str, Any], source_api_type: str) -> dict[str, Any]:
    if source_api_type == "responses" and "input" in body:
        result = _filter_fields(body, OPENAI_RESPONSES_FIELDS)
        _ensure_responses_reasoning_summary(result, body)
        return result

    items, instructions = _chat_as_responses(_messages_as_chat(body, source_api_type))
    result: dict[str, Any] = {"model": body.get("model", ""), "input": items}
    if instructions:
        result["instructions"] = instructions
    if "max_completion_tokens" in body:
        result["max_output_tokens"] = body["max_completion_tokens"]
    elif "max_tokens" in body:
        result["max_output_tokens"] = body["max_tokens"]
    if source_api_type == "claude":
        thinking_effort = _claude_thinking_to_reasoning_effort(body)
    else:
        thinking_effort = body.get("reasoning_effort") or _thinking_to_reasoning_effort(body.get("thinking"))
    if thinking_effort:
        result["reasoning"] = {"effort": thinking_effort}

    _copy_common_responses_params(body, result)
    _ensure_responses_reasoning_summary(result, body)
    return _filter_fields(result, OPENAI_RESPONSES_FIELDS)

def _ensure_responses_reasoning_summary(result: dict[str, Any], source: dict[str, Any]) -> None:
    if not request_uses_openai_reasoning(source):
        return

    reasoning = result.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning = {}
    reasoning["summary"] = "detailed"
    result["reasoning"] = reasoning

def _thinking_to_reasoning_effort(thinking: Any) -> str:
    if isinstance(thinking, str):
        return thinking if thinking in {"low", "medium", "high"} else ""
    if not isinstance(thinking, dict):
        return ""
    effort = thinking.get("effort")
    if effort in {"low", "medium", "high"}:
        return effort
    budget = thinking.get("budget_tokens")
    if not isinstance(budget, int):
        return ""
    if budget <= 1024:
        return "low"
    if budget <= 2048:
        return "medium"
    return "high"

def _claude_thinking_to_reasoning_effort(body: dict[str, Any]) -> str:
    output_config = body.get("output_config")
    if isinstance(output_config, dict) and output_config.get("effort"):
        return str(output_config["effort"])
    return _thinking_to_reasoning_effort(body.get("thinking"))

def _openai_to_claude_thinking_effort(body: dict[str, Any]) -> str:
    if body.get("reasoning_effort"):
        return str(body["reasoning_effort"])
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        return str(reasoning["effort"])
    return ""

def _to_claude_request(body: dict[str, Any], source_api_type: str) -> dict[str, Any]:
    if source_api_type == "claude" and "messages" in body:
        return _filter_fields(body, CLAUDE_FIELDS)

    messages, system = _chat_as_claude(_messages_as_chat(body, source_api_type))

    result: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": messages,
        "max_tokens": body.get("max_output_tokens", body.get("max_completion_tokens", body.get("max_tokens", 1024))),
    }
    if system:
        result["system"] = system
    _copy_if_present(body, result, "temperature")
    _copy_if_present(body, result, "top_p")
    _copy_if_present(body, result, "top_k")
    _copy_if_present(body, result, "stream")
    _copy_if_present(body, result, "tools")
    _copy_if_present(body, result, "tool_choice")
    _copy_if_present(body, result, "thinking")
    _copy_if_present(body, result, "output_config")
    if "thinking" not in result:
        thinking_effort = _openai_to_claude_thinking_effort(body)
        if thinking_effort:
            result["thinking"] = {"type": "adaptive", "display": "summarized"}
            output_config = result.get("output_config")
            if not isinstance(output_config, dict):
                output_config = {}
            if "effort" not in output_config:
                output_config["effort"] = thinking_effort
            result["output_config"] = output_config
    if "stop" in body:
        result["stop_sequences"] = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]
    return _filter_fields(result, CLAUDE_FIELDS)

def _openai_content_to_claude(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return _content_to_text(content)

    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({"type": "text", "text": str(item)})
            continue
        if item.get("type") == "text":
            parts.append({"type": "text", "text": item.get("text", "")})
        elif item.get("type") == "image_url":
            image_url = item.get("image_url", {}).get("url", "")
            if isinstance(image_url, str) and image_url.startswith("data:"):
                parts.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_url.split(";", 1)[0].replace("data:", "") or "image/jpeg",
                        "data": image_url.split(",", 1)[-1],
                    },
                })
    return parts or ""

def _copy_if_present(source: dict[str, Any], target: dict[str, Any], key: str) -> None:
    if key in source and source[key] is not None:
        target[key] = source[key]

def _copy_common_openai_params(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in (
        "temperature", "top_p", "n", "stream", "stop", "presence_penalty",
        "frequency_penalty", "logit_bias", "user", "tools", "tool_choice",
        "parallel_tool_calls", "response_format", "seed", "logprobs", "top_logprobs",
        "stream_options", "modalities", "audio", "prediction", "service_tier",
        "metadata", "store",
    ):
        _copy_if_present(source, target, key)

def _copy_common_responses_params(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in (
        "include", "metadata", "parallel_tool_calls", "previous_response_id", "reasoning",
        "service_tier", "store", "stream", "temperature", "text", "tool_choice",
        "tools", "top_p", "truncation", "user", "output_config",
    ):
        _copy_if_present(source, target, key)

def _extract_openai_chat_text(response_body: dict[str, Any]) -> str:
    choices = response_body.get("choices", [])
    if not choices:
        return ""
    choice = choices[0]
    message = choice.get("message", {}) if isinstance(choice, dict) else {}
    return _content_to_text(message.get("content", choice.get("text", "")))

def _extract_responses_text(response_body: dict[str, Any]) -> str:
    if isinstance(response_body.get("output_text"), str):
        return response_body["output_text"]

    output_text = ""
    output = response_body.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        output_text += part.get("text") or part.get("output_text") or ""
    return output_text

def _extract_claude_text(response_body: dict[str, Any]) -> str:
    content = response_body.get("content", [])
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item.get("text", "") for item in content if isinstance(item, dict))
    return ""

def _to_responses_response(
    response_body: dict[str, Any],
    source_api_type: str,
    original_request: dict[str, Any],
) -> dict[str, Any]:
    text = _extract_claude_text(response_body) if source_api_type == "claude" else _extract_openai_chat_text(response_body)
    usage = response_body.get("usage", {}) if isinstance(response_body.get("usage"), dict) else {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    response_id = response_body.get("id", f"resp_{int(time.time())}")

    output = []
    for index, block in enumerate(_response_content_blocks(response_body, source_api_type)):
        item_id = f"item_{response_id}_{index}"
        if block["kind"] == "tool":
            call = block["call"]
            output.append({"id": item_id, "type": "function_call", "call_id": call["id"],
                           "name": call["function"]["name"], "arguments": call["function"]["arguments"], "status": "completed"})
        elif block["kind"] == "thinking":
            output.append({"id": item_id, "type": "reasoning", "summary": [{"type": "summary_text", "text": block["text"]}]})
        else:
            output.append({"id": item_id, "type": "message", "role": "assistant", "status": "completed",
                           "content": [{"type": "output_text", "text": block["text"], "annotations": []}]})

    return {
        "id": response_id,
        "object": "response",
        "created_at": response_body.get("created", int(time.time())),
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": original_request.get("instructions") or original_request.get("system"),
        "max_output_tokens": original_request.get("max_output_tokens") or original_request.get("max_tokens"),
        "model": response_body.get("model", original_request.get("model", "")),
        "output": output,
        "output_text": text,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": usage.get("total_tokens", input_tokens + output_tokens) or 0,
        },
    }

def _to_openai_chat_response(
    response_body: dict[str, Any],
    source_api_type: str,
    original_request: dict[str, Any],
) -> dict[str, Any]:
    if source_api_type == "responses":
        text = _extract_responses_text(response_body)
        usage = response_body.get("usage", {}) if isinstance(response_body.get("usage"), dict) else {}
        prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
        completion_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    else:
        text = _extract_claude_text(response_body)
        usage = response_body.get("usage", {}) if isinstance(response_body.get("usage"), dict) else {}
        prompt_tokens = usage.get("input_tokens", 0) or 0
        completion_tokens = usage.get("output_tokens", 0) or 0

    return {
        "id": response_body.get("id", f"chatcmpl-{int(time.time())}"),
        "object": "chat.completion",
        "created": response_body.get("created_at", response_body.get("created", int(time.time()))),
        "model": response_body.get("model", original_request.get("model", "")),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": response_body.get("stop_reason", "stop"),
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": usage.get("total_tokens", prompt_tokens + completion_tokens) or 0,
        },
    }

def _to_claude_response(
    response_body: dict[str, Any],
    source_api_type: str,
    original_request: dict[str, Any],
) -> dict[str, Any]:
    usage = response_body.get("usage", {}) if isinstance(response_body.get("usage"), dict) else {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0

    content_blocks = []
    for block in _response_content_blocks(response_body, source_api_type):
        if block["kind"] == "tool":
            call = block["call"]
            content_blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                                   "input": _tool_arguments(call["function"]["arguments"])})
        elif block["kind"] == "thinking":
            content_blocks.append({"type": "thinking", "thinking": block["text"],
                                   "signature": make_compat_thinking_signature()})
        else:
            content_blocks.append({"type": "text", "text": block["text"]})
    if not content_blocks:
        content_blocks.append({"type": "text", "text": ""})

    stop_reason = "end_turn"
    if source_api_type != "responses":
        choices = response_body.get("choices", [])
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            fr = choice.get("finish_reason", "stop")
            stop_reason = "end_turn" if fr == "stop" else fr

    return {
        "id": response_body.get("id", f"msg_{int(time.time())}"),
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": response_body.get("model", original_request.get("model", "")),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("Tool arguments must contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be a JSON object")
    return parsed


def _convert_tools(result: dict[str, Any], body: dict[str, Any], source: str, target: str) -> None:
    if source == target:
        return
    if "tools" in body:
        tools = []
        for tool in body["tools"] or []:
            if source == "claude":
                if tool.get("type") not in (None, "custom"):
                    raise ValueError("Provider-native tools cannot be converted between protocols")
                fn = {"name": tool["name"], "parameters": tool.get("input_schema", {})}
                if "description" in tool:
                    fn["description"] = tool["description"]
            else:
                if tool.get("type") != "function":
                    raise ValueError("Provider-native tools cannot be converted between protocols")
                fn = dict(tool.get("function") or {}) if source == "openai" else {k: v for k, v in tool.items() if k != "type"}
            if target == "openai":
                tools.append({"type": "function", "function": fn})
            elif target == "responses":
                tools.append({"type": "function", **fn})
            else:
                converted = {"name": fn["name"], "input_schema": fn.get("parameters", {})}
                if "description" in fn:
                    converted["description"] = fn["description"]
                tools.append(converted)
        result["tools"] = tools
    choice = body.get("tool_choice")
    if choice is None and target == "claude" and body.get("tools") and body.get("parallel_tool_calls") is False:
        choice = "auto"
    if choice is not None:
        name = None
        if isinstance(choice, dict):
            if source == "openai":
                name = (choice.get("function") or {}).get("name")
            else:
                name = choice.get("name")
            mode = choice.get("type", "auto")
        else:
            mode = choice
        if target == "claude":
            result["tool_choice"] = {"type": "tool", "name": name} if name else {"type": "any" if mode == "required" else mode}
            if body.get("parallel_tool_calls") is False:
                result["tool_choice"]["disable_parallel_tool_use"] = True
        else:
            mode = "required" if mode == "any" else mode
            result["tool_choice"] = ({"type": "function", "function": {"name": name}} if target == "openai" else {"type": "function", "name": name}) if name else mode
            if isinstance(choice, dict) and choice.get("disable_parallel_tool_use"):
                result["parallel_tool_calls"] = False


def _messages_as_chat(body: dict[str, Any], source: str) -> list[dict[str, Any]]:
    if source == "openai":
        return [dict(m) for m in body.get("messages", []) if isinstance(m, dict)]
    messages: list[dict[str, Any]] = []
    system = body.get("system") if source == "claude" else body.get("instructions")
    if system:
        messages.append({"role": "system", "content": _content_to_text(system)})
    if source == "responses":
        items = body.get("input", "")
        if isinstance(items, str):
            return messages + [{"role": "user", "content": items}]
        for item in items or []:
            if not isinstance(item, dict):
                messages.append({"role": "user", "content": str(item)})
            elif item.get("type") == "function_call":
                call = {"id": item["call_id"], "type": "function", "function": {"name": item["name"], "arguments": item.get("arguments", "{}")}}
                if messages and messages[-1].get("role") == "assistant" and "tool_calls" in messages[-1]:
                    messages[-1]["tool_calls"].append(call)
                else:
                    messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            elif item.get("type") == "function_call_output":
                output = item.get("output", "")
                messages.append({"role": "tool", "tool_call_id": item["call_id"], "content": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)})
            elif item.get("type", "message") == "message":
                messages.append({"role": item.get("role", "user"), "content": _responses_content_to_openai(item.get("content", ""))})
        return messages
    for msg in body.get("messages", []):
        role, content = msg.get("role", "user"), msg.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        parts, calls, results = [], [], []
        for block in content or []:
            kind = block.get("type")
            if kind == "tool_use":
                calls.append({"id": block["id"], "type": "function", "function": {"name": block["name"], "arguments": json.dumps(block.get("input", {}), ensure_ascii=False)}})
            elif kind == "tool_result":
                output = block.get("content", "")
                results.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": output if isinstance(output, str) else _content_to_text(output)})
            elif kind == "text":
                parts.append({"type": "text", "text": block.get("text", "")})
            elif kind == "image":
                image = block.get("source") or {}
                url = image.get("url") or f"data:{image.get('media_type', 'image/png')};base64,{image.get('data', '')}"
                parts.append({"type": "image_url", "image_url": {"url": url}})
        # Tool results must directly follow the assistant's tool call; any
        # accompanying user text is a separate message after those results.
        messages.extend(results)
        if parts or calls:
            converted: dict[str, Any] = {"role": role, "content": parts or None}
            if calls:
                converted["tool_calls"] = calls
            messages.append(converted)
    return messages


def _chat_as_responses(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    items, instructions = [], []
    for msg in messages:
        role, content = msg.get("role", "user"), msg.get("content")
        if role in ("system", "developer"):
            instructions.append(_content_to_text(content))
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": msg["tool_call_id"], "output": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)})
        else:
            if content:
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if part.get("type") == "text":
                            parts.append({"type": "output_text" if role == "assistant" else "input_text", "text": part.get("text", "")})
                        elif part.get("type") == "image_url":
                            parts.append({"type": "input_image", "image_url": part["image_url"]["url"]})
                    content = parts
                items.append({"role": role, "content": content})
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                items.append({"type": "function_call", "call_id": call["id"], "name": fn["name"], "arguments": fn.get("arguments", "{}")})
    return items, "\n".join(instructions)


def _chat_as_claude(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    items, system = [], []
    for msg in messages:
        role, content = msg.get("role", "user"), msg.get("content")
        if role in ("system", "developer"):
            system.append(_content_to_text(content))
            continue
        if role == "tool":
            converted = [{"type": "tool_result", "tool_use_id": msg["tool_call_id"], "content": content or ""}]
            role = "user"
        else:
            converted = _openai_content_to_claude(content)
            if isinstance(converted, str):
                converted = [{"type": "text", "text": converted}] if converted else []
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                converted.append({"type": "tool_use", "id": call["id"], "name": fn["name"], "input": _tool_arguments(fn.get("arguments"))})
        if items and items[-1]["role"] == role:
            items[-1]["content"].extend(converted)
        else:
            items.append({"role": role, "content": converted})
    return items, "\n".join(system)


def _response_tool_calls(body: dict[str, Any], source: str) -> list[dict[str, Any]]:
    if source == "openai":
        choices = body.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("tool_calls") or []
    calls = []
    for item in body.get("content" if source == "claude" else "output", []):
        if source == "claude" and item.get("type") == "tool_use":
            calls.append({"id": item["id"], "type": "function", "function": {
                "name": item["name"], "arguments": json.dumps(item.get("input", {}), ensure_ascii=False)}})
        elif source == "responses" and item.get("type") == "function_call":
            calls.append({"id": item["call_id"], "type": "function", "function": {
                "name": item["name"], "arguments": item.get("arguments", "{}")}})
    return calls


def _response_content_blocks(body: dict[str, Any], source: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if source == "openai":
        choices = body.get("choices") or [{}]
        message = choices[0].get("message") or {}
        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if reasoning:
            blocks.append({"kind": "thinking", "text": reasoning})
        text = _extract_openai_chat_text(body)
        if text:
            blocks.append({"kind": "text", "text": text})
        blocks.extend({"kind": "tool", "call": c} for c in _response_tool_calls(body, source))
        return blocks
    for item in body.get("content" if source == "claude" else "output", []):
        kind = item.get("type")
        if kind in ("text", "thinking"):
            blocks.append({"kind": kind, "text": item.get("text") or item.get("thinking", "")})
        elif kind == "message":
            blocks.extend({"kind": "text", "text": part.get("text", "")} for part in item.get("content", []) if part.get("type") == "output_text")
        elif kind == "reasoning":
            for parts in (item.get("summary") or [], item.get("content") or []):
                blocks.extend({"kind": "thinking", "text": part.get("text", "")} for part in parts
                              if part.get("type") in ("summary_text", "reasoning_text", "text"))
        elif kind in ("tool_use", "function_call"):
            wrapped = {"content" if source == "claude" else "output": [item]}
            blocks.extend({"kind": "tool", "call": c} for c in _response_tool_calls(wrapped, source))
    return blocks
