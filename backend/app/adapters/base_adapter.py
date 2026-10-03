import re
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from urllib.parse import urlsplit


_PROTECTED_HEADERS = {"authorization", "api-key", "x-api-key"}
_API_VERSION = re.compile(r"v\d+(?:\.\d+)*(?:(?:alpha|beta)\d*)?", re.IGNORECASE)


def build_upstream_url(base_url: str, endpoint: str) -> str:
    url = urlsplit(base_url.strip())
    base = url.path.rstrip("/")
    path = "/" + endpoint.strip("/")

    if not base.endswith(path):
        version, separator, resource = path[1:].partition("/")
        if separator and _API_VERSION.fullmatch(version):
            suffix = "/" + resource
            # Keep an explicitly configured version, including full endpoint URLs.
            version_base = base[:-len(suffix)] if base.endswith(suffix) else base
            if _API_VERSION.fullmatch(version_base.rsplit("/", 1)[-1]):
                base, path = version_base, suffix
        base += path

    return url._replace(path=base).geturl()


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
        return build_upstream_url(base_url, "/v1/chat/completions")

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
