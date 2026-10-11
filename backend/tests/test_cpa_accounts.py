import unittest
from datetime import datetime, timedelta, timezone

from app.services import cpa_accounts, cpa_manager


NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def _account(**overrides):
    entry = {
        "name": "acc1.json",
        "type": "codex",
        "provider": "codex",
        "status": "active",
        "disabled": False,
        "unavailable": False,
        "success": 10,
        "failed": 0,
    }
    entry.update(overrides)
    return entry


class TimestampParsingTests(unittest.TestCase):
    def test_parses_utc_z_suffix(self):
        parsed = cpa_accounts.parse_timestamp("2026-10-12T12:00:00Z")
        self.assertEqual(parsed, NOW)

    def test_truncates_long_fractional_seconds(self):
        parsed = cpa_accounts.parse_timestamp("2026-10-12T12:00:00.123456789Z")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.microsecond, 123456)

    def test_parses_offset_without_colon(self):
        parsed = cpa_accounts.parse_timestamp("2026-10-12T20:00:00+0800")
        self.assertEqual(parsed, NOW)

    def test_naive_timestamp_is_treated_as_utc(self):
        self.assertEqual(cpa_accounts.parse_timestamp("2026-10-12T12:00:00"), NOW)

    def test_invalid_values_return_none(self):
        for value in (None, "", "not-a-time", 12345):
            self.assertIsNone(cpa_accounts.parse_timestamp(value))


class AccountAvailabilityTests(unittest.TestCase):
    def test_plain_active_account_is_available(self):
        self.assertTrue(cpa_accounts.account_is_available(_account(), NOW))

    def test_disabled_flag_blocks_account(self):
        self.assertFalse(cpa_accounts.account_is_available(_account(disabled=True), NOW))

    def test_disabled_status_blocks_account(self):
        self.assertFalse(cpa_accounts.account_is_available(_account(status="disabled"), NOW))

    def test_unavailable_blocks_account(self):
        self.assertFalse(cpa_accounts.account_is_available(_account(unavailable=True), NOW))

    def test_future_next_retry_blocks_account(self):
        future = (NOW + timedelta(minutes=5)).isoformat()
        self.assertFalse(
            cpa_accounts.account_is_available(_account(next_retry_after=future), NOW)
        )

    def test_expired_next_retry_does_not_block_account(self):
        past = (NOW - timedelta(minutes=5)).isoformat()
        self.assertTrue(
            cpa_accounts.account_is_available(_account(next_retry_after=past), NOW)
        )

    def test_credential_scope_cooldown_blocks_account(self):
        entry = _account(
            unavailable=True,
            cooldowns=[{"scope": "auth", "reason": "unauthorized", "remaining_seconds": 60}],
        )
        self.assertFalse(cpa_accounts.account_is_available(entry, NOW))

    def test_model_scope_cooldown_keeps_account_available(self):
        # CPA 仍会用该账号服务其它模型，因此不能把整个账号判为不可用。
        entry = _account(
            cooldowns=[
                {"scope": "model", "model_key": "gpt-5", "remaining_seconds": 900}
            ]
        )
        self.assertTrue(cpa_accounts.account_is_available(entry, NOW))

    def test_expired_cooldown_snapshot_does_not_block(self):
        entry = _account(cooldowns=[{"scope": "auth", "retry_at": "2026-10-12T11:00:00Z"}])
        self.assertTrue(cpa_accounts.account_is_available(entry, NOW))


class AccountStateTests(unittest.TestCase):
    def test_active_state(self):
        self.assertEqual(cpa_accounts.account_state(_account(), NOW), "active")

    def test_degraded_when_some_models_cooling(self):
        entry = _account(cooldowns=[{"scope": "model", "remaining_seconds": 300}])
        self.assertEqual(cpa_accounts.account_state(entry, NOW), "degraded")

    def test_cooling_state_for_timed_cooldown(self):
        entry = _account(
            status="error",
            unavailable=True,
            next_retry_after=(NOW + timedelta(minutes=10)).isoformat(),
        )
        self.assertEqual(cpa_accounts.account_state(entry, NOW), "cooling")

    def test_error_state_without_recovery_time(self):
        entry = _account(status="error", unavailable=True, status_message="token expired")
        self.assertEqual(cpa_accounts.account_state(entry, NOW), "error")

    def test_disabled_takes_precedence(self):
        entry = _account(disabled=True, status="error", unavailable=True)
        self.assertEqual(cpa_accounts.account_state(entry, NOW), "disabled")


class SummarizeAccountsTests(unittest.TestCase):
    def test_pool_with_one_available_account_is_healthy(self):
        files = [
            _account(name="a.json", status="error", unavailable=True),
            _account(name="b.json"),
            _account(name="c.json", disabled=True),
        ]
        summary = cpa_accounts.summarize_accounts(files, NOW)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["available"], 1)
        self.assertEqual(summary["disabled"], 1)
        self.assertTrue(summary["healthy"])

    def test_all_accounts_unusable_is_unhealthy(self):
        files = [
            _account(name="a.json", status="error", unavailable=True),
            _account(name="b.json", disabled=True),
        ]
        summary = cpa_accounts.summarize_accounts(files, NOW)
        self.assertEqual(summary["available"], 0)
        self.assertFalse(summary["healthy"])

    def test_empty_pool_is_unhealthy(self):
        summary = cpa_accounts.summarize_accounts([], NOW)
        self.assertEqual(summary["total"], 0)
        self.assertFalse(summary["healthy"])

    def test_summary_ignores_non_dict_entries(self):
        summary = cpa_accounts.summarize_accounts([_account(), "junk"], NOW)  # type: ignore[list-item]
        self.assertEqual(summary["total"], 1)
        self.assertTrue(summary["healthy"])


class SerializeAccountTests(unittest.TestCase):
    def test_serializes_core_fields(self):
        entry = _account(
            name="acc1.json",
            email="user@example.com",
            priority=3,
            weight=2,
            cooldowns=[{"scope": "auth", "remaining_seconds": 120, "reason": "unauthorized"}],
        )
        payload = cpa_accounts.serialize_account(entry, NOW)
        self.assertEqual(payload["name"], "acc1.json")
        self.assertEqual(payload["email"], "user@example.com")
        self.assertEqual(payload["provider_label"], "OpenAI Codex")
        self.assertEqual(payload["priority"], 3)
        # 凭据级冷却生效时账号不可调度，界面状态应显示为冷却中。
        self.assertEqual(payload["state"], "cooling")
        self.assertFalse(payload["available"])
        self.assertEqual(len(payload["cooldowns"]), 1)

    def test_unknown_provider_label_falls_back_to_raw_value(self):
        payload = cpa_accounts.serialize_account(_account(provider="brand-new"), NOW)
        self.assertEqual(payload["provider_label"], "brand-new")


class ChecksumParsingTests(unittest.TestCase):
    def test_parses_checksums_file(self):
        text = (
            "abc123  CLIProxyAPI_8.0.22_linux_amd64.tar.gz\n"
            "DEF456 *CLIProxyAPI_8.0.22_linux_aarch64.tar.gz\n"
            "\n"
            "malformed-line\n"
        )
        checksums = cpa_manager.parse_checksums(text)
        self.assertEqual(checksums["CLIProxyAPI_8.0.22_linux_amd64.tar.gz"], "abc123")
        self.assertEqual(checksums["CLIProxyAPI_8.0.22_linux_aarch64.tar.gz"], "def456")
        self.assertEqual(len(checksums), 2)


class PlatformAssetTests(unittest.TestCase):
    def test_asset_name_strips_version_prefix(self):
        from unittest.mock import patch

        with patch("app.services.cpa_manager.platform.system", return_value="Linux"), patch(
            "app.services.cpa_manager.platform.machine", return_value="x86_64"
        ):
            asset = cpa_manager.platform_asset_name("v8.0.22")
        self.assertEqual(asset, "CLIProxyAPI_8.0.22_linux_amd64.tar.gz")

    def test_unsupported_architecture_raises(self):
        from unittest.mock import patch

        with patch("app.services.cpa_manager.platform.system", return_value="Linux"), patch(
            "app.services.cpa_manager.platform.machine", return_value="mips"
        ):
            with self.assertRaises(cpa_manager.CpaError):
                cpa_manager.platform_asset_name("8.0.22")


class ChannelNamingTests(unittest.TestCase):
    def test_channel_name_uses_account_type_label(self):
        self.assertEqual(cpa_manager.channel_name_for_provider("claude"), "CliProxyAPI-Claude Code")
        self.assertEqual(cpa_manager.channel_name_for_provider("codex"), "CliProxyAPI-OpenAI Codex")
        self.assertEqual(cpa_manager.CPA_CHANNEL_PREFIX, "CliProxyAPI-")

    def test_unknown_provider_falls_back_to_raw_key(self):
        self.assertEqual(cpa_manager.channel_name_for_provider("acme"), "CliProxyAPI-acme")


if __name__ == "__main__":
    unittest.main()
