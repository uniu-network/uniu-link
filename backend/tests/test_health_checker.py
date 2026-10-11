import importlib.util
import unittest
from types import SimpleNamespace
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


class _FakeSession:
    def __init__(self, instance):
        self._instance = instance

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._instance)


class _FakeResult:
    def __init__(self, instance):
        self._instance = instance

    def scalar_one_or_none(self):
        return self._instance


def _account_pool_channel(provider: str | None = None):
    return Channel(
        id="channel-cpa",
        name="CliProxyAPI-primary",
        provider="cliproxyapi",
        api_type="openai",
        base_url="http://127.0.0.1:8317",
        encrypted_api_key="encrypted",
        health_check_mode="account_pool",
        cpa_instance_id="instance-1",
        cpa_provider=provider,
    )


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


@unittest.skipUnless(HAS_BACKEND_DEPS, "backend dependencies are not installed")
class AccountPoolHealthTests(unittest.IsolatedAsyncioTestCase):
    """托管渠道按账号类型拆分：实例运行且该类型下仍有可调度账号才算健康。"""

    def setUp(self):
        from app.services import cpa_accounts, cpa_manager

        self.instance = SimpleNamespace(id="instance-1", name="primary", pid=4321)
        self.cpa_manager = cpa_manager
        self.cpa_accounts = cpa_accounts

    async def _check(self, *, running: bool, files: list, provider: str | None = None) -> bool:
        with (
            patch(
                "app.core.database.AsyncSessionLocal",
                return_value=_FakeSession(self.instance),
            ),
            patch.object(
                self.cpa_manager, "is_instance_running", AsyncMock(return_value=running)
            ),
            patch.object(
                self.cpa_accounts, "list_auth_files", AsyncMock(return_value=files)
            ),
        ):
            return await health_checker.check_channel_health(_account_pool_channel(provider))

    async def test_healthy_pool_marks_channel_healthy(self):
        files = [
            {"name": "a.json", "status": "error", "unavailable": True},
            {"name": "b.json", "status": "active", "unavailable": False},
        ]
        self.assertTrue(await self._check(running=True, files=files))

    async def test_all_accounts_unusable_marks_channel_unhealthy(self):
        files = [
            {"name": "a.json", "status": "disabled", "disabled": True},
            {"name": "b.json", "status": "error", "unavailable": True},
        ]
        self.assertFalse(await self._check(running=True, files=files))

    async def test_stopped_instance_marks_channel_unhealthy(self):
        files = [{"name": "b.json", "status": "active", "unavailable": False}]
        self.assertFalse(await self._check(running=False, files=files))

    async def test_channel_without_instance_is_unhealthy(self):
        channel = _account_pool_channel()
        channel.cpa_instance_id = None
        self.assertFalse(await health_checker.check_channel_health(channel))

    async def test_channel_only_counts_its_own_account_type(self):
        """一种类型全部不可用时，不应连带把其它类型的渠道判为不健康。"""
        files = [
            {"name": "claude.json", "provider": "claude", "status": "disabled", "disabled": True},
            {"name": "codex.json", "provider": "codex", "status": "active", "unavailable": False},
        ]
        self.assertFalse(await self._check(running=True, files=files, provider="claude"))
        self.assertTrue(await self._check(running=True, files=files, provider="codex"))

    async def test_channel_without_matching_accounts_is_unhealthy(self):
        files = [
            {"name": "codex.json", "provider": "codex", "status": "active", "unavailable": False},
        ]
        self.assertFalse(await self._check(running=True, files=files, provider="claude"))


if __name__ == "__main__":
    unittest.main()
