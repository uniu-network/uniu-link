from abc import ABC, abstractmethod
from typing import AsyncGenerator


_PROTECTED_HEADERS = {"authorization", "api-key", "x-api-key"}


def merge_custom_headers(headers: dict, custom_headers: dict | None) -> dict:
    if not custom_headers:
        return headers
    merged = dict(headers)
    for key, value in custom_headers.items():
        if not isinstance(key, str):
            continue
        if key.lower() in _PROTECTED_HEADERS:
            continue
        merged[key] = str(value) if value is not None else ""
    return merged


class BaseAdapter(ABC):

    provider: str = "generic"

    default_base_url = ""

    @abstractmethod
    def convert_request(self, request_body: dict, api_type: str) -> dict:
        ...

    @abstractmethod
    def convert_response(self, response_body: dict, api_type: str, original_request: dict) -> dict:
        ...

    @abstractmethod
    def convert_error(self, status_code: int, error_body: dict, api_type: str) -> dict:
        ...

    def get_headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}"}

    def get_url(self, base_url: str, api_type: str) -> str:
        return f"{base_url.rstrip('/')}/v1/chat/completions"

    @abstractmethod
    async def convert_stream_chunk(
        self, chunk_data: str, api_type: str
    ) -> str | None:
        ...

    @abstractmethod
    def convert_stream_done(self, api_type: str) -> str:
        ...

    @abstractmethod
    def convert_to_openai_stream_chunk(self, chunk_data: str) -> str | None:
        ...

    @abstractmethod
    def convert_to_claude_stream_event(self, chunk_data: str, original_request: dict) -> str | None:
        ...

    def calculate_tokens(self, response_body: dict, api_type: str) -> dict:
        usage = response_body.get("usage", {}) if response_body else {}
        if not usage:
            usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        return usage
