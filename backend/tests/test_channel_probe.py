import unittest

from app.services.channel_probe import (
    build_models_url,
    build_prompt_request,
    extract_reply_text,
)
from app.adapters.base_adapter import build_upstream_url


class ChannelProbeTests(unittest.TestCase):
    def test_openai_text_content(self):
        response = {
            "choices": [{"message": {"content": "hello"}}],
        }
        self.assertEqual(extract_reply_text(response, "openai"), "hello")

    def test_openai_content_blocks(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "hello "},
                            {"type": "text", "text": "world"},
                        ]
                    }
                }
            ],
        }
        self.assertEqual(extract_reply_text(response, "openai"), "hello world")

    def test_openai_content_object(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": {"type": "text", "text": "hello"},
                    }
                }
            ],
        }
        self.assertEqual(extract_reply_text(response, "openai"), "hello")

    def test_openai_reasoning_fallback(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "probe succeeded",
                    }
                }
            ],
        }
        self.assertEqual(
            extract_reply_text(response, "openai"),
            "probe succeeded",
        )

    def test_responses_collects_all_text_parts(self):
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hello "},
                        {"type": "output_text", "text": "world"},
                    ],
                }
            ]
        }
        self.assertEqual(extract_reply_text(response, "responses"), "hello world")

    def test_claude_content(self):
        response = {
            "content": [
                {"type": "thinking", "thinking": "internal"},
                {"type": "text", "text": "hello"},
            ]
        }
        self.assertEqual(extract_reply_text(response, "claude"), "hello")

    def test_prompt_request_uses_protocol_token_field(self):
        request = build_prompt_request("responses", "model-a", "ping", 16)
        self.assertEqual(request["max_output_tokens"], 16)
        self.assertNotIn("max_tokens", request)

    def test_models_url_does_not_duplicate_v1(self):
        self.assertEqual(
            build_models_url("https://example.com/v1"),
            "https://example.com/v1/models",
        )
        self.assertEqual(
            build_models_url("https://example.com"),
            "https://example.com/v1/models",
        )

    def test_endpoint_url_does_not_duplicate_v1(self):
        self.assertEqual(
            build_upstream_url(
                "https://example.com/v1",
                "/v1/chat/completions",
            ),
            "https://example.com/v1/chat/completions",
        )
        self.assertEqual(
            build_upstream_url(
                "https://example.com",
                "/v1/responses",
            ),
            "https://example.com/v1/responses",
        )


if __name__ == "__main__":
    unittest.main()
