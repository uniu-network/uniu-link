import base64
import json
import time
import uuid
from contextvars import ContextVar
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.routing_engine import ChannelInfo

_claude_passthrough_thinking_block_open: ContextVar[bool] = ContextVar(
    "_claude_passthrough_thinking_block_open", default=False
)
_claude_passthrough_thinking_block_index: ContextVar[int] = ContextVar(
    "_claude_passthrough_thinking_block_index", default=-1
)

class ClaudeStreamState:

    def __init__(self) -> None:
        self.message_started: bool = False
        self.thinking_block_started: bool = False
        self.thinking_block_stopped: bool = False
        self.text_block_started: bool = False
        self.text_block_stopped: bool = False
        self.model: str = ""
        self.message_id: str = ""
        self.message_stopped: bool = False

    def _sse(self, event_type: str, data: dict[str, Any]) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def emit_message_start(self, model: str = "", msg_id: str = "") -> str:
        if self.message_started:
            return ""
        self.message_started = True
        self.model = model
        self.message_id = msg_id or f"msg_{int(time.time())}"
        return self._sse("message_start", {
            "type": "message_start",
            "message": {
                "id": self.message_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": "",
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        })

    def emit_thinking_start(self) -> str:
        if self.thinking_block_started:
            return ""
        self.thinking_block_started = True
        return self._sse("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        })

    def emit_thinking_delta(self, thinking: str) -> str:
        if not thinking:
            return ""
        return self._sse("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": thinking},
        })

    def emit_thinking_stop(self) -> str:
        if self.thinking_block_stopped or not self.thinking_block_started:
            return ""
        self.thinking_block_stopped = True
        return self._sse("content_block_stop", {
            "type": "content_block_stop",
            "index": 0,
        })

    def emit_text_start(self) -> str:
        if self.text_block_started:
            return ""
        parts = []
        if self.thinking_block_started and not self.thinking_block_stopped:
            parts.append(self.emit_thinking_stop())
        self.text_block_started = True
        idx = 1 if self.thinking_block_started else 0
        parts.append(self._sse("content_block_start", {
            "type": "content_block_start",
            "index": idx,
            "content_block": {"type": "text", "text": ""},
        }))
        self._text_index = idx
        return "".join(parts)

    def emit_text_delta(self, text: str) -> str:
        if not text:
            return ""
        idx = getattr(self, "_text_index", 0)
        return self._sse("content_block_delta", {
            "type": "content_block_delta",
            "index": idx,
            "delta": {"type": "text_delta", "text": text},
        })

    def emit_text_stop(self) -> str:
        if self.text_block_stopped or not self.text_block_started:
            return ""
        self.text_block_stopped = True
        idx = getattr(self, "_text_index", 0)
        return self._sse("content_block_stop", {
            "type": "content_block_stop",
            "index": idx,
        })

    def emit_message_delta(self, stop_reason: str = "end_turn",
                           input_tokens: int = 0, output_tokens: int = 0) -> str:
        return self._sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        })

    def emit_message_stop(self) -> str:
        if self.message_stopped:
            return ""
        self.message_stopped = True
        parts = []
        if self.text_block_started and not self.text_block_stopped:
            parts.append(self.emit_text_stop())
        if self.thinking_block_started and not self.thinking_block_stopped:
            parts.append(self.emit_thinking_stop())
        parts.append(self._sse("message_stop", {"type": "message_stop"}))
        return "".join(parts)

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
    return provider in ("openai", "azure", "custom", "google")

def transform_request_body(
    request_body: dict[str, Any],
    source_api_type: str,
    target_api_type: str,
) -> dict[str, Any]:
    source = normalize_api_type(source_api_type)
    target = normalize_api_type(target_api_type)

    if target == "auto":
        target = "responses" if request_uses_openai_reasoning(request_body) else "openai"

    if target == "openai":
        return _to_openai_chat_request(request_body, source)
    if target == "responses":
        return _to_responses_request(request_body, source)
    if target == "claude":
        return _to_claude_request(request_body, source)
    return dict(request_body)

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
        return response_body
    if target == "openai":
        return _to_openai_chat_response(response_body, source, original_request)
    if target == "responses":
        return _to_responses_response(response_body, source, original_request)
    if target == "claude":
        return _to_claude_response(response_body, source, original_request)
    return response_body

def transform_stream_chunk(
    chunk_data: str,
    source_api_type: str,
    target_api_type: str,
    claude_state: ClaudeStreamState | None = None,
) -> str | None:
    source = normalize_api_type(source_api_type)
    target = normalize_api_type(target_api_type)

    if target == "auto":
        target = "openai"

    if source == target:
        if is_stream_done_chunk(chunk_data) and claude_state is not None and not claude_state.message_stopped:
            parts = [_ensure_sse_frame(chunk_data) or ""]
            parts.append(claude_state.emit_message_delta())
            parts.append(claude_state.emit_message_stop())
            result = "".join(parts)
            return result if result.strip() else None
        if source == "claude":
            return _patch_claude_sse_frame(chunk_data)
        return _ensure_sse_frame(chunk_data)

    if is_stream_done_chunk(chunk_data):
        if target == "claude" and claude_state is not None:
            parts = []
            if not claude_state.message_stopped:
                if claude_state.text_block_started and not claude_state.text_block_stopped:
                    parts.append(claude_state.emit_text_stop())
                if claude_state.thinking_block_started and not claude_state.thinking_block_stopped:
                    parts.append(claude_state.emit_thinking_stop())
                if claude_state.message_started and not claude_state.message_stopped:
                    parts.append(claude_state.emit_message_delta())
                    parts.append(claude_state.emit_message_stop())
            result = "".join(parts)
            return result if result else None
        if source == target == "responses":
            return _ensure_sse_frame(chunk_data)
        return stream_done_marker(target)
    if source == "openai" and target == "responses":
        return _openai_stream_to_responses(chunk_data)
    if source == "openai" and target == "claude":
        return _openai_stream_to_claude(chunk_data, claude_state)
    if source == "claude" and target == "openai":
        return _claude_stream_to_openai(chunk_data)
    if source == "claude" and target == "responses":
        return _claude_stream_to_responses(chunk_data)
    if source == "responses" and target == "openai":
        return _responses_stream_to_openai(chunk_data)
    if source == "responses" and target == "claude":
        return _responses_stream_to_claude(chunk_data, claude_state)
    return _ensure_sse_frame(chunk_data)

def stream_done_marker(api_type: str) -> str:
    normalized = normalize_api_type(api_type)
    if normalized == "auto":
        normalized = "openai"
    if normalized == "claude":
        return "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"
    if normalized == "responses":
        created_at = int(time.time())
        event_data = {
            "type": "response.completed",
            "sequence_number": 0,
            "response": {
                "id": f"resp_proxy_{created_at}",
                "object": "response",
                "created_at": created_at,
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "model": "",
                "output": [],
            },
        }
        return f"event: response.completed\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    return "data: [DONE]\n\n"

def is_stream_done_chunk(chunk_data: str) -> bool:
    if not chunk_data:
        return False
    data = chunk_data.strip()
    if "data: [DONE]" in data:
        return True
    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return False
    return payload.get("type") in {"message_stop", "response.completed"}

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

def _responses_content_to_claude(content: Any) -> str | list[dict[str, Any]]:
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
            image_url = item.get("image_url") or item.get("url") or ""
            if isinstance(image_url, str) and image_url.startswith("data:"):
                parts.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_url.split(";", 1)[0].replace("data:", "") or "image/jpeg",
                        "data": image_url.split(",", 1)[-1],
                    },
                })
        else:
            text = item.get("text") or item.get("content")
            if text:
                parts.append({"type": "text", "text": str(text)})

    return parts or ""

def _to_openai_chat_request(body: dict[str, Any], source_api_type: str) -> dict[str, Any]:
    if source_api_type == "openai" and "messages" in body:
        return _filter_fields(body, OPENAI_CHAT_FIELDS)

    if source_api_type == "claude":
        messages: list[dict[str, Any]] = []
        system = body.get("system")
        if system:
            messages.append({"role": "system", "content": _content_to_text(system)})
        for msg in body.get("messages", []):
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "user")
            if role not in ("user", "assistant", "system", "developer", "tool"):
                role = "user"
            messages.append({"role": role, "content": _content_to_text(msg.get("content", ""))})

        result: dict[str, Any] = {"model": body.get("model", ""), "messages": messages}
        _copy_if_present(body, result, "max_tokens")
        _copy_if_present(body, result, "temperature")
        _copy_if_present(body, result, "top_p")
        if "stop_sequences" in body:
            result["stop"] = body["stop_sequences"]
        _copy_common_openai_params(body, result)
        return _filter_fields(result, OPENAI_CHAT_FIELDS)

    messages = []
    instructions = body.get("instructions")
    if instructions:
        messages.append({"role": "system", "content": _content_to_text(instructions)})

    input_value = body.get("input", body.get("prompt", ""))
    if isinstance(input_value, str):
        messages.append({"role": "user", "content": input_value})
    elif isinstance(input_value, list):
        for item in input_value:
            if not isinstance(item, dict):
                messages.append({"role": "user", "content": str(item)})
                continue
            role = item.get("role", "user")
            if role in ("system", "developer"):
                role = "system"
            elif role not in ("user", "assistant", "tool"):
                role = "user"
            messages.append({"role": role, "content": _responses_content_to_openai(item.get("content", ""))})
    elif input_value:
        messages.append({"role": "user", "content": str(input_value)})

    result = {"model": body.get("model", ""), "messages": messages}
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

    result: dict[str, Any] = {"model": body.get("model", "")}

    if source_api_type == "claude":
        if body.get("system"):
            result["instructions"] = _content_to_text(body.get("system"))
        result["input"] = [
            {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            for msg in body.get("messages", [])
            if isinstance(msg, dict)
        ]
        if "max_tokens" in body:
            result["max_output_tokens"] = body["max_tokens"]
        if "stop_sequences" in body:
            result["stop"] = body["stop_sequences"]
        thinking_effort = _claude_thinking_to_reasoning_effort(body)
        if thinking_effort:
            result["reasoning"] = {"effort": thinking_effort}
    else:
        input_items = []
        instructions = []
        for msg in body.get("messages", []):
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("system", "developer"):
                text = _content_to_text(content)
                if text:
                    instructions.append(text)
            else:
                input_items.append({"role": role if role in ("user", "assistant") else "user", "content": content})
        if instructions:
            result["instructions"] = "\n".join(instructions)
        result["input"] = input_items or body.get("prompt", "")
        if "max_completion_tokens" in body:
            result["max_output_tokens"] = body["max_completion_tokens"]
        elif "max_tokens" in body:
            result["max_output_tokens"] = body["max_tokens"]
        if "reasoning_effort" in body:
            result["reasoning"] = {"effort": body["reasoning_effort"]}
        thinking_effort = _thinking_to_reasoning_effort(body.get("thinking"))
        if thinking_effort and "reasoning" not in result:
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

    messages: list[dict[str, Any]] = []
    system_parts = []

    if source_api_type == "responses":
        instructions = body.get("instructions")
        if instructions:
            system_parts.append(_content_to_text(instructions))

        input_value = body.get("input", "")
        if isinstance(input_value, str):
            messages.append({"role": "user", "content": input_value})
        elif isinstance(input_value, list):
            for item in input_value:
                if not isinstance(item, dict):
                    messages.append({"role": "user", "content": str(item)})
                    continue
                role = item.get("role", "user")
                content = _responses_content_to_claude(item.get("content", ""))
                if role in ("system", "developer"):
                    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                    if text:
                        system_parts.append(text)
                elif role == "assistant":
                    messages.append({"role": "assistant", "content": content})
                else:
                    messages.append({"role": "user", "content": content})
        elif input_value:
            messages.append({"role": "user", "content": str(input_value)})
    else:
        for msg in body.get("messages", []):
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("system", "developer"):
                text = _content_to_text(content)
                if text:
                    system_parts.append(text)
            elif role in ("user", "assistant"):
                messages.append({"role": role, "content": _openai_content_to_claude(content)})
            elif role == "tool":
                messages.append({"role": "user", "content": json.dumps(msg, ensure_ascii=False)})

    result: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": messages,
        "max_tokens": body.get("max_output_tokens", body.get("max_completion_tokens", body.get("max_tokens", 1024))),
    }
    if system_parts:
        result["system"] = "\n".join(system_parts)
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
        "output": [
            {
                "id": f"msg_{response_id}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
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

    content_blocks: list[dict[str, Any]] = []

    if source_api_type == "responses":
        output = response_body.get("output", [])
        for item in (output if isinstance(output, list) else []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "reasoning":
                summary_text = ""
                for summary in item.get("summary", []):
                    if isinstance(summary, dict) and summary.get("type") == "summary_text":
                        summary_text += summary.get("text", "")
                if summary_text:
                    content_blocks.append({"type": "thinking", "thinking": summary_text})
            elif item.get("type") == "message":
                for part in item.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        content_blocks.append({"type": "text", "text": part.get("text", "")})
        if not content_blocks:
            text = _extract_responses_text(response_body)
            if text:
                content_blocks.append({"type": "text", "text": text})
    else:
        choices = response_body.get("choices", [])
        if isinstance(choices, list) and choices:
            choice = choices[0] if isinstance(choices[0], dict) else {}
            msg = choice.get("message", {}) if isinstance(choice.get("message"), dict) else {}
            reasoning = msg.get("reasoning_content", "")
            if reasoning:
                content_blocks.append({"type": "thinking", "thinking": reasoning})
            text = msg.get("content", "")
            if text:
                content_blocks.append({"type": "text", "text": text})
        if not content_blocks:
            text = _extract_openai_chat_text(response_body)
            if text:
                content_blocks.append({"type": "text", "text": text})

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

def _ensure_sse_frame(chunk_data: str) -> str | None:
    if not chunk_data:
        return None
    return chunk_data if chunk_data.endswith("\n\n") else f"{chunk_data}\n\n"

def _patch_claude_sse_frame(chunk_data: str) -> str | None:
    framed = _ensure_sse_frame(chunk_data)
    if not framed:
        return None

    payload = _extract_sse_payload(framed)
    if not payload:
        return framed

    event_type = payload.get("type", "")

    if event_type == "content_block_start":
        block = payload.get("content_block")
        if not isinstance(block, dict):
            return framed

        needs_rebuild = False

        if block.get("type") == "thinking":
            if "signature" not in block:
                block["signature"] = ""
                needs_rebuild = True
            _claude_passthrough_thinking_block_open.set(True)
            _claude_passthrough_thinking_block_index.set(payload.get("index", 0))
        elif block.get("type") == "text":
            if "citations" not in block:
                block["citations"] = None
                needs_rebuild = True
        elif block.get("type") == "tool_use":
            if "citations" not in block:
                block["citations"] = None
                needs_rebuild = True

        if needs_rebuild:
            return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    if event_type == "content_block_stop":
        thinking_active = _claude_passthrough_thinking_block_open.get()
        thinking_idx = _claude_passthrough_thinking_block_index.get()
        stop_idx = payload.get("index", -1)

        if thinking_active and stop_idx == thinking_idx:
            _claude_passthrough_thinking_block_open.set(False)
            raw_sig = uuid.uuid4().hex + uuid.uuid4().hex
            signature = base64.b64encode(raw_sig.encode()).decode()
            sig_delta = f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': thinking_idx, 'delta': {'type': 'signature_delta', 'signature': signature}}, ensure_ascii=False)}\n\n"
            return sig_delta + framed

    return framed

def _extract_sse_payload(chunk_data: str) -> dict[str, Any] | None:
    for line in chunk_data.strip().split("\n"):
        if line.startswith("data:"):
            data = line.replace("data:", "", 1).strip()
            if not data or data == "[DONE]":
                return None
            try:
                return json.loads(data)
            except Exception:
                return None
    return None

def _openai_stream_text(chunk_data: str) -> str:
    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return ""

    if payload.get("type") == "response.output_text.delta":
        return _stream_value_to_text(payload.get("delta", ""))

    for key in (
        "delta", "content", "text", "output_text", "reasoning_content",
        "reasoning", "reasoning_text", "thinking", "thought",
    ):
        text = _stream_value_to_text(payload.get(key))
        if text:
            return text

    choices = payload.get("choices", [])
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta", {})

    text = _stream_value_to_text(delta)
    if text:
        return text

    delta_dict = delta if isinstance(delta, dict) else {}
    for key in (
        "content", "text", "output_text", "reasoning_content", "reasoning",
        "reasoning_text", "thinking", "thought",
    ):
        text = _stream_value_to_text(delta_dict.get(key))
        if text:
            return text

    message = choice.get("message", {}) if isinstance(choice.get("message"), dict) else {}
    for key in (
        "content", "text", "output_text", "reasoning_content", "reasoning",
        "reasoning_text", "thinking", "thought",
    ):
        text = _stream_value_to_text(message.get(key) or choice.get(key))
        if text:
            return text

    return ""

def _stream_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "".join(_stream_value_to_text(item) for item in value)
    if isinstance(value, dict):
        for key in (
            "content", "text", "output_text", "delta", "value", "reasoning_content",
            "reasoning", "reasoning_text", "thinking", "thought",
        ):
            text = _stream_value_to_text(value.get(key))
            if text:
                return text
    return ""

def _claude_stream_text(chunk_data: str) -> str:
    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return ""
    delta = payload.get("delta", {}) if isinstance(payload.get("delta"), dict) else {}
    return _content_to_text(delta.get("text", ""))

def _responses_stream_text(chunk_data: str) -> str:
    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return ""
    if payload.get("type") == "response.output_text.delta":
        return _content_to_text(payload.get("delta", ""))
    return ""

def _responses_stream_reasoning_text(chunk_data: str) -> str:
    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return ""
    if payload.get("type") in (
        "response.reasoning_summary_text.delta",
        "response.reasoning_text.delta",
    ):
        return _content_to_text(payload.get("delta", ""))
    return ""

def _openai_stream_to_responses(chunk_data: str) -> str | None:
    payload = _extract_sse_payload(chunk_data)
    if isinstance(payload, dict) and str(payload.get("type", "")).startswith("response."):
        event_type = payload.get("type", "response.event")
        return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    text = _openai_stream_text(chunk_data)
    if not text:
        return None
    event_data = {
        "type": "response.output_text.delta",
        "output_index": 0,
        "content_index": 0,
        "delta": text,
    }
    return f"event: response.output_text.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

def _openai_stream_to_claude(
    chunk_data: str,
    state: ClaudeStreamState | None = None,
) -> str | None:
    if state is None:
        text = _openai_stream_text(chunk_data)
        if not text:
            return None
        event_data = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
        return f"event: content_block_delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return None

    parts: list[str] = []

    obj = payload.get("object", "")
    choices = payload.get("choices", [])
    choice = choices[0] if isinstance(choices, list) and choices else {}
    delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    model = payload.get("model", "")

    if obj == "chat.completion.chunk" and delta.get("role") == "assistant":
        parts.append(state.emit_message_start(model=model))

    reasoning = delta.get("reasoning_content", "")
    if reasoning:
        if not state.message_started:
            parts.append(state.emit_message_start(model=model))
        if not state.thinking_block_started:
            parts.append(state.emit_thinking_start())
        parts.append(state.emit_thinking_delta(reasoning))

    content = delta.get("content", "")
    if content:
        if not state.message_started:
            parts.append(state.emit_message_start(model=model))
        if not state.text_block_started:
            parts.append(state.emit_text_start())
        parts.append(state.emit_text_delta(content))

    if finish_reason:
        stop_reason = "end_turn" if finish_reason == "stop" else finish_reason
        if state.text_block_started and not state.text_block_stopped:
            parts.append(state.emit_text_stop())
        if state.thinking_block_started and not state.thinking_block_stopped:
            parts.append(state.emit_thinking_stop())
        if state.message_started and not state.message_stopped:
            parts.append(state.emit_message_delta(stop_reason=stop_reason))
            parts.append(state.emit_message_stop())

    result = "".join(parts)
    return result if result else None

def _claude_stream_to_openai(chunk_data: str) -> str | None:
    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return None
    event_type = payload.get("type", "")

    if event_type == "message_start":
        message = payload.get("message", {})
        event_data = {
            "id": message.get("id", "chatcmpl-stream"),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": message.get("model", ""),
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        }
        return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    elif event_type == "content_block_delta":
        delta = payload.get("delta", {})
        delta_type = delta.get("type", "")

        if delta_type == "thinking_delta":
            thinking = delta.get("thinking", "")
            if thinking:
                event_data = {
                    "id": "chatcmpl-stream",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "",
                    "choices": [{"index": 0, "delta": {"reasoning_content": thinking}, "finish_reason": None}],
                }
                return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

        elif delta_type == "text_delta":
            text = delta.get("text", "")
            if text:
                event_data = {
                    "id": "chatcmpl-stream",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "",
                    "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
                }
                return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    elif event_type == "message_delta":
        stop_reason = payload.get("delta", {}).get("stop_reason")
        if stop_reason:
            finish_reason = "stop" if stop_reason == "end_turn" else stop_reason
            event_data = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            }
            return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    elif event_type == "message_stop":
        return "data: [DONE]\n\n"

    return None

def _claude_stream_to_responses(chunk_data: str) -> str | None:
    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return None
    event_type = payload.get("type", "")

    if event_type == "message_start":
        message = payload.get("message", {})
        resp_id = message.get("id", f"resp_{int(time.time())}")
        event_data = {
            "type": "response.created",
            "response": {
                "id": resp_id,
                "object": "response",
                "created_at": int(time.time()),
                "status": "in_progress",
                "model": message.get("model", ""),
                "output": [],
            },
        }
        return f"event: response.created\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    elif event_type == "content_block_start":
        block = payload.get("content_block", {})
        block_type = block.get("type", "")
        index = payload.get("index", 0)

        if block_type == "thinking":
            event_data = {
                "type": "response.output_item.added",
                "output_index": index,
                "item": {
                    "type": "reasoning",
                    "id": f"rs_{int(time.time())}_{index}",
                    "summary": [{"type": "summary_text", "text": ""}],
                },
            }
            return f"event: response.output_item.added\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

        elif block_type == "text":
            parts = []
            item_event = {
                "type": "response.output_item.added",
                "output_index": index,
                "item": {
                    "type": "message",
                    "id": f"msg_{int(time.time())}_{index}",
                    "status": "in_progress",
                    "role": "assistant",
                    "content": [],
                },
            }
            parts.append(f"event: response.output_item.added\ndata: {json.dumps(item_event, ensure_ascii=False)}\n\n")
            content_event = {
                "type": "response.content_part.added",
                "output_index": index,
                "content_index": 0,
                "part": {"type": "output_text", "text": ""},
            }
            parts.append(f"event: response.content_part.added\ndata: {json.dumps(content_event, ensure_ascii=False)}\n\n")
            return "".join(parts)

    elif event_type == "content_block_delta":
        delta = payload.get("delta", {})
        delta_type = delta.get("type", "")
        index = payload.get("index", 0)

        if delta_type == "thinking_delta":
            thinking = delta.get("thinking", "")
            if thinking:
                event_data = {
                    "type": "response.reasoning_summary_text.delta",
                    "output_index": index,
                    "summary_index": 0,
                    "delta": thinking,
                }
                return f"event: response.reasoning_summary_text.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

        elif delta_type == "text_delta":
            text = delta.get("text", "")
            if text:
                event_data = {
                    "type": "response.output_text.delta",
                    "output_index": index,
                    "content_index": 0,
                    "delta": text,
                }
                return f"event: response.output_text.delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    elif event_type == "message_stop":
        event_data = {
            "type": "response.completed",
            "response": {
                "id": f"resp_{int(time.time())}",
                "object": "response",
                "created_at": int(time.time()),
                "status": "completed",
            },
        }
        return f"event: response.completed\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    return None

def _responses_stream_to_openai(chunk_data: str) -> str | None:
    reasoning_text = _responses_stream_reasoning_text(chunk_data)
    if reasoning_text:
        event_data = {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "choices": [{"index": 0, "delta": {"reasoning_content": reasoning_text}, "finish_reason": None}],
        }
        return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    text = _responses_stream_text(chunk_data)
    if not text:
        return None
    event_data = {
        "id": "chatcmpl-stream",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

def _responses_stream_to_claude(
    chunk_data: str,
    state: ClaudeStreamState | None = None,
) -> str | None:
    if state is None:
        reasoning_text = _responses_stream_reasoning_text(chunk_data)
        if reasoning_text:
            event_data = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": reasoning_text},
            }
            return f"event: content_block_delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

        text = _responses_stream_text(chunk_data)
        if not text:
            return None
        event_data = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
        return f"event: content_block_delta\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

    payload = _extract_sse_payload(chunk_data)
    if not payload:
        return None

    event_type = payload.get("type", "")
    parts: list[str] = []

    if event_type == "response.created":
        resp = payload.get("response", {})
        model = resp.get("model", "")
        msg_id = resp.get("id", "")
        parts.append(state.emit_message_start(model=model, msg_id=msg_id))

    elif event_type == "response.output_item.added":
        item = payload.get("item", {})
        item_type = item.get("type", "")
        if item_type == "reasoning":
            if not state.message_started:
                parts.append(state.emit_message_start())
            if not state.thinking_block_started:
                parts.append(state.emit_thinking_start())
        elif item_type == "message":
            if not state.message_started:
                parts.append(state.emit_message_start())
            if not state.text_block_started:
                parts.append(state.emit_text_start())

    elif event_type == "response.content_part.added":
        if not state.message_started:
            parts.append(state.emit_message_start())
        if not state.text_block_started:
            parts.append(state.emit_text_start())

    elif event_type in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
        reasoning = payload.get("delta", "")
        if reasoning:
            if not state.message_started:
                parts.append(state.emit_message_start())
            if not state.thinking_block_started:
                parts.append(state.emit_thinking_start())
            parts.append(state.emit_thinking_delta(str(reasoning)))

    elif event_type == "response.output_text.delta":
        text = payload.get("delta", "")
        if text:
            if not state.message_started:
                parts.append(state.emit_message_start())
            if not state.text_block_started:
                parts.append(state.emit_text_start())
            parts.append(state.emit_text_delta(str(text)))

    elif event_type == "response.completed":
        if state.text_block_started and not state.text_block_stopped:
            parts.append(state.emit_text_stop())
        if state.thinking_block_started and not state.thinking_block_stopped:
            parts.append(state.emit_thinking_stop())
        if state.message_started and not state.message_stopped:
            resp = payload.get("response", {})
            status = resp.get("status", "completed")
            stop_reason = "end_turn" if status == "completed" else status
            parts.append(state.emit_message_delta(stop_reason=stop_reason))
            parts.append(state.emit_message_stop())

    result = "".join(parts)
    return result if result else None
