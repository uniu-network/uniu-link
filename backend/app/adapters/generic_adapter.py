import json
from app.adapters.base_adapter import BaseAdapter, build_upstream_url


class GenericAdapter(BaseAdapter):

    provider = "generic"

    def convert_request(self, request_body: dict, api_type: str) -> dict:
        return request_body

    def convert_response(self, response_body: dict, api_type: str, original_request: dict) -> dict:
        return response_body

    def convert_error(self, status_code: int, error_body: dict, api_type: str) -> dict:
        if api_type in ("openai", "responses"):
            return {
                "error": {
                    "message": str(error_body),
                    "type": "api_error",
                    "code": str(status_code),
                }
            }
        elif api_type == "claude":
            return {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": str(error_body),
                },
            }
        return error_body

    def get_headers(self, api_key: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def get_url(self, base_url: str, api_type: str) -> str:
        if api_type == "claude":
            return build_upstream_url(base_url, "/v1/messages")
        if api_type == "responses":
            return build_upstream_url(base_url, "/v1/responses")
        return build_upstream_url(base_url, "/v1/chat/completions")

    async def convert_stream_chunk(self, chunk_data: str, api_type: str) -> str | None:
        return chunk_data

    def convert_stream_done(self, api_type: str) -> str:
        if api_type in ("openai", "responses"):
            return "data: [DONE]\n\n"
        return "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"

    def convert_to_openai_stream_chunk(self, chunk_data: str) -> str | None:
        return chunk_data

    def convert_to_claude_stream_event(self, chunk_data: str, original_request: dict) -> str | None:
        return chunk_data


def get_adapter(provider: str):
    from app.adapters.openai_adapter import OpenAIAdapter
    from app.adapters.anthropic_adapter import AnthropicAdapter
    from app.adapters.azure_adapter import AzureAdapter

    adapters = {
        "openai": OpenAIAdapter(),
        "anthropic": AnthropicAdapter(),
        "azure": AzureAdapter(),
        "google": GenericAdapter(),
        "custom": GenericAdapter(),
        # CLIProxyAPI 原生提供 OpenAI / Responses / Claude 三种协议入口，
        # 因此直接复用通用适配器，只负责拼接对应的上游路径。
        "cliproxyapi": GenericAdapter(),
    }

    return adapters.get(provider, GenericAdapter())
