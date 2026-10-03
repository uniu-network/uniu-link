from typing import Any

from app.adapters.base_adapter import build_upstream_url
from app.services.request_transformer import normalize_api_type


def build_models_url(base_url: str) -> str:
    return build_upstream_url(base_url, "/v1/models")


def build_prompt_request(
    api_type: str,
    model: str,
    message: str,
    max_tokens: int,
) -> dict[str, Any]:
    normalized = normalize_api_type(api_type)
    if normalized == "claude":
        return {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": max_tokens,
        }
    if normalized == "responses":
        return {
            "model": model,
            "input": message,
            "max_output_tokens": max_tokens,
        }
    return {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": max_tokens,
    }


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        value = (
            content.get("text")
            or content.get("output_text")
            or content.get("content")
        )
        return _content_to_text(value)
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            value = (
                item.get("text")
                or item.get("output_text")
                or item.get("content")
            )
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)


def extract_reply_text(response: dict[str, Any], api_type: str) -> str:
    normalized = normalize_api_type(api_type)

    if normalized == "claude":
        return _content_to_text(response.get("content"))

    if normalized == "responses":
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        parts: list[str] = []
        output = response.get("output", [])
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                text = _content_to_text(item.get("content"))
                if text:
                    parts.append(text)
        return "".join(parts)

    choices = response.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""

    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message")
    if isinstance(message, dict):
        text = _content_to_text(message.get("content"))
        if text:
            return text

        # Some OpenAI-compatible reasoning models only populate a reasoning
        # field for short probes even though the request itself succeeded.
        for key in ("reasoning_content", "reasoning", "analysis"):
            reasoning = _content_to_text(message.get(key))
            if reasoning:
                return reasoning

    return _content_to_text(choice.get("text"))
