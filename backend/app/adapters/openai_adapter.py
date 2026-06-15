import json
from app.adapters.base_adapter import BaseAdapter


class OpenAIAdapter(BaseAdapter):

    provider = "openai"

    def convert_request(self, request_body: dict, api_type: str) -> dict:
        if api_type in ("openai", "responses"):
            return request_body

        if api_type == "claude":
            return self._claude_to_openai(request_body)

        return request_body

    def _claude_to_openai(self, request_body: dict) -> dict:
        openai_body = {
            "model": request_body.get("model", ""),
        }

        system_content = request_body.get("system", "")
        messages = []

        if system_content:
            if isinstance(system_content, str):
                messages.append({"role": "system", "content": system_content})
            elif isinstance(system_content, list):
                text_parts = [
                    p.get("text", "") for p in system_content if p.get("type") == "text"
                ]
                messages.append({"role": "system", "content": " ".join(text_parts)})

        for msg in request_body.get("messages", []):
            role = msg.get("role", "user")
            if role == "assistant":
                role = "assistant"
            elif role == "user":
                role = "user"

            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    p.get("text", "") for p in content if p.get("type") == "text"
                ]
                content = " ".join(text_parts)

            messages.append({"role": role, "content": content})

        openai_body["messages"] = messages

        if "max_tokens" in request_body:
            openai_body["max_tokens"] = request_body["max_tokens"]
        if "temperature" in request_body:
            openai_body["temperature"] = request_body["temperature"]
        if "top_p" in request_body:
            openai_body["top_p"] = request_body["top_p"]
        if "stop_sequences" in request_body:
            openai_body["stop"] = request_body["stop_sequences"]
        if "stream" in request_body:
            openai_body["stream"] = request_body["stream"]

        return openai_body

    def convert_response(self, response_body: dict, api_type: str, original_request: dict) -> dict:
        if api_type in ("openai", "responses"):
            return response_body

        if api_type == "claude":
            return self._openai_to_claude(response_body, original_request)

        return response_body

    def _openai_to_claude(self, response_body: dict, original_request: dict) -> dict:
        choices = response_body.get("choices", [])
        claude_content = []

        if choices:
            choice = choices[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            if content:
                claude_content.append({"type": "text", "text": content})

        claude_response = {
            "id": response_body.get("id", "msg_unknown"),
            "type": "message",
            "role": "assistant",
            "content": claude_content,
            "model": response_body.get("model", original_request.get("model", "")),
            "stop_reason": (choices[0].get("finish_reason", "end_turn") if choices else "end_turn"),
            "stop_sequence": None,
        }

        usage = response_body.get("usage", {})
        if usage:
            claude_response["usage"] = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }

        return claude_response

    def convert_error(self, status_code: int, error_body: dict, api_type: str) -> dict:
        message = error_body.get("error", {}).get("message", "Unknown error")

        if api_type in ("openai", "responses"):
            return {
                "error": {
                    "message": message,
                    "type": "api_error",
                    "code": str(status_code),
                }
            }
        elif api_type == "claude":
            return {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": message,
                },
            }

        return error_body

    def get_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def get_url(self, base_url: str, api_type: str) -> str:
        if api_type == "responses":
            return f"{base_url.rstrip('/')}/v1/responses"
        return f"{base_url.rstrip('/')}/v1/chat/completions"

    async def convert_stream_chunk(self, chunk_data: str, api_type: str) -> str | None:
        if api_type in ("openai", "responses"):
            return chunk_data
        elif api_type == "claude":
            return self.convert_to_claude_stream_event(chunk_data, {})
        return chunk_data

    def convert_stream_done(self, api_type: str) -> str:
        if api_type in ("openai", "responses"):
            return "data: [DONE]\n\n"
        return ""

    def convert_to_openai_stream_chunk(self, chunk_data: str) -> str | None:
        return chunk_data

    def convert_to_claude_stream_event(self, chunk_data: str, original_request: dict) -> str | None:
        try:
            data = chunk_data.strip()
            if not data.startswith("data: "):
                return None
            json_str = data[6:]
            if json_str == "[DONE]":
                return "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"

            chunk = json.loads(json_str)
            choices = chunk.get("choices", [])
            if not choices:
                return None

            choice = choices[0]
            delta = choice.get("delta", {})
            content = delta.get("content", "")

            if content:
                event_data = {
                    "type": "content_block_delta",
                    "index": choice.get("index", 0),
                    "delta": {"type": "text_delta", "text": content},
                }
                return f"event: content_block_delta\ndata: {json.dumps(event_data)}\n\n"

            if choice.get("index", 0) == 0 and not content:
                event_data = {
                    "type": "message_start",
                    "message": {
                        "id": chunk.get("id", ""),
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": chunk.get("model", ""),
                    },
                }
                return f"event: message_start\ndata: {json.dumps(event_data)}\n\n"
        except Exception:
            pass
        return None
