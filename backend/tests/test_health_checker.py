import importlib.util
import unittest
from unittest.mock import AsyncMock, patch


HAS_BACKEND_DEPS = importlib.util.find_spec("httpx") is not None

if HAS_BACKEND_DEPS:
    from app.models.channel import Channel
    from app.services import health_checker


class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    def __init__(self):
        self.get = AsyncMock(return_value=_FakeResponse(404, "not found"))
        self.post = AsyncMock(return_value=_FakeResponse(200, "{}"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@unittest.skipUnless(HAS_BACKEND_DEPS, "backend dependencies are not installed")
class HealthCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_list_failure_falls_back_to_prompt_probe(self):
        channel = Channel(
            id="channel-1",
            name="compatible-upstream",
            provider="custom",
            api_type="openai",
            base_url="https://example.com/v1",
            encrypted_api_key="encrypted",
            timeout=15,
            upstream_models=["model-a"],
            health_check_mode="model_list",
            health_check_model="model-a",
            health_check_prompt="ping",
            health_check_max_tokens=8,
        )
        client = _FakeAsyncClient()

        with (
            patch.object(
                health_checker.key_encryption,
                "decrypt",
                return_value="api-key",
            ),
            patch.object(
                health_checker.httpx,
                "AsyncClient",
                return_value=client,
            ),
        ):
            healthy = await health_checker.check_channel_health(channel)

        self.assertTrue(healthy)
        client.get.assert_awaited_once_with(
            "https://example.com/v1/models",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer api-key",
            },
        )
        self.assertEqual(client.post.await_count, 1)
        self.assertEqual(
            client.post.await_args.args[0],
            "https://example.com/v1/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
