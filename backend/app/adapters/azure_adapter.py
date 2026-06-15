import json
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
                return f"{base_url.rstrip('/')}/v1/responses"
            return f"{base_url.rstrip('/')}/v1/chat/completions"
        return base_url
