import json
import time
from app.adapters.base_adapter import BaseAdapter


class AnthropicAdapter(BaseAdapter):

    provider = "anthropic"

    def convert_request(self, request_body: dict, api_type: str) -> dict:
        if api_type == "claude":
            return request_body

        if api_type == "openai":
            return self._openai_to_anthropic(request_body)

        if api_type == "responses":
            return self._responses_to_anthropic(request_body)

        return request_body

    def _responses_content_to_anthropic(self, content) -> str | list[dict]:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content) if content is not None else ""

        parts = []
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

    def _responses_to_anthropic(self, request_body: dict) -> dict:
        messages = []
        system_parts = []
        instructions = request_body.get("instructions")
        if instructions:
            system_parts.append(str(instructions))

        input_value = request_body.get("input", "")
        if isinstance(input_value, str):
            messages.append({"role": "user", "content": input_value})
        elif isinstance(input_value, list):
            for item in input_value:
                if not isinstance(item, dict):
                    messages.append({"role": "user", "content": str(item)})
                    continue

                role = item.get("role", "user")
                content = self._responses_content_to_anthropic(item.get("content", ""))
                if role in ("system", "developer"):
                    if content:
                        system_parts.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
                elif role == "assistant":
                    messages.append({"role": "assistant", "content": content})
                else:
                    messages.append({"role": "user", "content": content})
        elif input_value:
            messages.append({"role": "user", "content": str(input_value)})

        anthropic_body = {
            "model": request_body.get("model", ""),
            "messages": messages,
            "max_tokens": request_body.get("max_output_tokens", request_body.get("max_tokens", 1024)),
        }

        if system_parts:
            anthropic_body["system"] = "\n".join(system_parts)
        if "temperature" in request_body:
            anthropic_body["temperature"] = request_body["temperature"]
        if "top_p" in request_body:
            anthropic_body["top_p"] = request_body["top_p"]
        if "stop" in request_body:
            anthropic_body["stop_sequences"] = (
                request_body["stop"] if isinstance(request_body["stop"], list) else [request_body["stop"]]
            )
        if "stream" in request_body:
            anthropic_body["stream"] = request_body["stream"]

        return anthropic_body

    def _openai_to_anthropic(self, request_body: dict) -> dict:
        messages = []
        system_content = ""

        for msg in request_body.get("messages", []):
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                system_content = content if isinstance(content, str) else str(content)
            elif role in ("user", "assistant"):
                if isinstance(content, str):
                    messages.append({"role": role, "content": content})
                elif isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if item.get("type") == "text":
                            text_parts.append({"type": "text", "text": item["text"]})
                        elif item.get("type") == "image_url":
                            text_parts.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": item.get("image_url", {}).get("url", "").split(",")[-1]
                                    if item.get("image_url", {}).get("url", "").startswith("data:") else "",
                                },
                            })
                    messages.append({"role": role, "content": text_parts})
                else:
                    messages.append({"role": role, "content": str(content)})
            elif role == "tool":
                messages.append({"role": "user", "content": json.dumps(msg)})

        anthropic_body = {
            "model": request_body.get("model", ""),
            "messages": messages,
            "max_tokens": request_body.get("max_tokens", 1024),
        }

        if system_content:
            anthropic_body["system"] = system_content
        if "temperature" in request_body:
            anthropic_body["temperature"] = request_body["temperature"]
        if "top_p" in request_body:
            anthropic_body["top_p"] = request_body["top_p"]
        if "stop" in request_body:
            anthropic_body["stop_sequences"] = (
                request_body["stop"] if isinstance(request_body["stop"], list) else [request_body["stop"]]
            )
        if "stream" in request_body:
            anthropic_body["stream"] = request_body["stream"]

        return anthropic_body

    def convert_response(self, response_body: dict, api_type: str, original_request: dict) -> dict:
        if api_type == "claude":
            return response_body

        if api_type == "openai":
            return self._anthropic_to_openai(response_body, original_request)

        if api_type == "responses":
            return self._anthropic_to_responses(response_body, original_request)

        return response_body

    def _anthropic_to_responses(self, response_body: dict, original_request: dict) -> dict:
        content_items = response_body.get("content", [])
        output_text = ""
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                output_text += item.get("text", "")

        usage = response_body.get("usage", {})
        input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
        output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
        response_id = response_body.get("id", f"resp_{int(time.time())}")
        created_at = int(time.time())

        return {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "instructions": original_request.get("system"),
            "max_output_tokens": original_request.get("max_tokens"),
            "model": response_body.get("model", original_request.get("model", "")),
            "output": [
                {
                    "id": f"msg_{response_id}",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output_text,
                            "annotations": [],
                        }
                    ],
                }
            ],
            "parallel_tool_calls": True,
            "previous_response_id": None,
            "reasoning": None,
            "store": True,
            "temperature": original_request.get("temperature"),
            "text": {"format": {"type": "text"}},
            "tool_choice": "auto",
            "tools": [],
            "top_p": original_request.get("top_p"),
            "truncation": "disabled",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }

    def _anthropic_to_openai(self, response_body: dict, original_request: dict) -> dict:
        content_items = response_body.get("content", [])
        content_text = ""
        for item in content_items:
            if item.get("type") == "text":
                content_text += item.get("text", "")

        model = original_request.get("model", response_body.get("model", ""))

        openai_response = {
            "id": response_body.get("id", f"chatcmpl-{int(time.time())}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content_text,
                    },
                    "finish_reason": response_body.get("stop_reason", "stop"),
                }
            ],
        }

        usage = response_body.get("usage", {})
        if usage:
            openai_response["usage"] = {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            }

        return openai_response

    def convert_error(self, status_code: int, error_body: dict, api_type: str) -> dict:
        message = error_body.get("error", {}).get("message", str(error_body))

        if api_type == "claude":
            return {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": message,
                },
            }
        elif api_type in ("openai", "responses"):
            return {
                "error": {
                    "message": message,
                    "type": "api_error",
                    "code": str(status_code),
                }
            }
        return error_body

    def get_headers(self, api_key: str) -> dict:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def get_url(self, base_url: str, api_type: str) -> str:
        return f"{base_url.rstrip('/')}/v1/messages"

    async def convert_stream_chunk(self, chunk_data: str, api_type: str) -> str | None:
        if api_type == "claude":
            return chunk_data
        elif api_type == "openai":
            return self.convert_to_openai_stream_chunk(chunk_data)
        elif api_type == "responses":
            return self.convert_to_responses_stream_event(chunk_data)
        return chunk_data

    def convert_stream_done(self, api_type: str) -> str:
        if api_type == "claude":
            return "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"
        if api_type == "responses":
            return "data: [DONE]\n\n"
        return "data: [DONE]\n\n"

    def convert_to_openai_stream_chunk(self, chunk_data: str) -> str | None:
        try:
            lines = chunk_data.strip().split("\n")
            for line in lines:
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    event_type = data.get("type", "")

                    if event_type == "message_start":
                        message = data.get("message", {})
                        openai_chunk = {
                            "id": message.get("id", "chatcmpl-stream"),
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": message.get("model", ""),
                            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                        }
                        return f"data: {json.dumps(openai_chunk)}\n\n"

                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        delta_type = delta.get("type", "")

                        if delta_type == "thinking_delta":
                            thinking = delta.get("thinking", "")
                            if thinking:
                                openai_chunk = {
                                    "id": "chatcmpl-stream",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": "",
                                    "choices": [{"index": 0, "delta": {"reasoning_content": thinking}, "finish_reason": None}],
                                }
                                return f"data: {json.dumps(openai_chunk)}\n\n"

                        elif delta_type == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                openai_chunk = {
                                    "id": "chatcmpl-stream",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": "",
                                    "choices": [{"index": data.get("index", 0), "delta": {"content": text}, "finish_reason": None}],
                                }
                                return f"data: {json.dumps(openai_chunk)}\n\n"

                    elif event_type == "message_delta":
                        stop_reason = data.get("delta", {}).get("stop_reason")
                        if stop_reason:
                            finish_reason = "stop" if stop_reason == "end_turn" else stop_reason
                            openai_chunk = {
                                "id": "chatcmpl-stream",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": "",
                                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                            }
                            return f"data: {json.dumps(openai_chunk)}\n\n"

                    elif event_type == "message_stop":
                        return "data: [DONE]\n\n"
        except Exception:
            pass
        return None

    def convert_to_claude_stream_event(self, chunk_data: str, original_request: dict) -> str | None:
        return chunk_data

    def convert_to_responses_stream_event(self, chunk_data: str) -> str | None:
        try:
            data = chunk_data.strip()
            if not data.startswith("data: "):
                return None

            payload = json.loads(data[6:])
            event_type = payload.get("type", "")

            if event_type == "message_start":
                message = payload.get("message", {})
                event_data = {
                    "type": "response.created",
                    "response": {
                        "id": message.get("id", f"resp_{int(time.time())}"),
                        "object": "response",
                        "created_at": int(time.time()),
                        "status": "in_progress",
                        "model": message.get("model", ""),
                        "output": [],
                    },
                }
                return f"event: response.created\ndata: {json.dumps(event_data)}\n\n"

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
                    return f"event: response.output_item.added\ndata: {json.dumps(event_data)}\n\n"

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
                    parts.append(f"event: response.output_item.added\ndata: {json.dumps(item_event)}\n\n")
                    content_event = {
                        "type": "response.content_part.added",
                        "output_index": index,
                        "content_index": 0,
                        "part": {"type": "output_text", "text": ""},
                    }
                    parts.append(f"event: response.content_part.added\ndata: {json.dumps(content_event)}\n\n")
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
                        return f"event: response.reasoning_summary_text.delta\ndata: {json.dumps(event_data)}\n\n"

                elif delta_type == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        event_data = {
                            "type": "response.output_text.delta",
                            "output_index": index,
                            "content_index": 0,
                            "delta": text,
                        }
                        return f"event: response.output_text.delta\ndata: {json.dumps(event_data)}\n\n"

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
                return f"event: response.completed\ndata: {json.dumps(event_data)}\n\n"
        except Exception:
            pass
        return None
