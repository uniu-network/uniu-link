import json
from app.adapters.base_adapter import build_upstream_url
from app.adapters.openai_adapter import OpenAIAdapter


class AzureAdapter(OpenAIAdapter):

    provider = "azure"

    def get_headers(self, api_key: str) -> dict:
        return {
            "api-key": api_key,
            "Content-Type": "application/json",
        }

    def get_url(self, base_url: str, api_type: str) -> str:
        if "deployments" not in base_url:
            if api_type == "responses":
                return build_upstream_url(base_url, "/v1/responses")
            return build_upstream_url(base_url, "/v1/chat/completions")
        return base_url
