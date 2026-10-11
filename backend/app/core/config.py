from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

YAML_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_CONFIG_PATH = PROJECT_ROOT / ".env"

SENSITIVE_KEYS: set[str] = {
    "encryption_key", "admin_api_key", "postgres_password",
}

CONFIG_META: dict[str, tuple[type, Any, bool, str]] = {
    "app_name": (str, "UniuLink", False, "应用名称"),
    "app_env": (str, "production", False, "运行环境"),
    "encryption_key": (str, "", False, "加密密钥"),
    "admin_api_key": (str, "admin-secret-key-change-me", False, "管理员 API 密钥"),
    "admin_hmac_ttl_seconds": (int, 300, False, "HMAC 签名有效期(秒)"),
    "postgres_host": (str, "localhost", False, "数据库主机"),
    "postgres_port": (int, 5432, False, "数据库端口"),
    "postgres_db": (str, "uniulink", False, "数据库名称"),
    "postgres_user": (str, "uniulink", False, "数据库用户"),
    "postgres_password": (str, "uniulink-secret-password", False, "数据库密码"),
    "redis_url": (str, "redis://localhost:6379/0", False, "Redis 连接地址"),
    "default_channel_timeout": (int, 30, True, "默认渠道超时(秒)"),
    "default_max_retries": (int, 2, True, "默认最大重试次数"),
    "health_check_interval": (int, 30, True, "健康检查间隔(秒)"),
    "circuit_breaker_failure_threshold": (int, 5, True, "熔断失败阈值"),
    "circuit_breaker_cooldown_seconds": (int, 60, True, "熔断冷却时间(秒)"),
    "circuit_breaker_half_open_max_requests": (int, 3, True, "熔断半开最大请求数"),
    "rate_limit_global_rps": (int, 1000, True, "全局速率限制(RPS)"),
    "rate_limit_per_key_rps": (int, 100, True, "每密钥速率限制(RPS)"),
    "rate_limit_per_model_rps": (int, 200, True, "每模型速率限制(RPS)"),
    "log_level": (str, "INFO", True, "日志级别"),
    "log_file": (str, "", True, "日志文件路径"),
    "raw_json_log": (bool, False, True, "原始 JSON 日志"),
    "log_body": (bool, False, True, "记录请求体"),
    "log_content": (bool, False, True, "记录响应内容"),
}

YAML_SECTION_MAP: dict[str, list[str]] = {
    "app": ["app_name", "app_env", "encryption_key",
            "admin_api_key", "admin_hmac_ttl_seconds"],
    "database": ["postgres_host", "postgres_port", "postgres_db", "postgres_user", "postgres_password"],
    "redis": ["redis_url"],
    "gateway": ["default_channel_timeout", "default_max_retries", "health_check_interval"],
    "circuit_breaker": ["circuit_breaker_failure_threshold", "circuit_breaker_cooldown_seconds",
                        "circuit_breaker_half_open_max_requests"],
    "rate_limit": ["rate_limit_global_rps", "rate_limit_per_key_rps", "rate_limit_per_model_rps"],
    "logging": ["log_level", "log_file", "raw_json_log", "log_body", "log_content"],
}

YAML_KEY_ALIASES: dict[str, dict[str, str]] = {
    "app": {
        "name": "app_name",
        "env": "app_env",
    },
    "database": {
        "host": "postgres_host",
        "port": "postgres_port",
        "name": "postgres_db",
        "user": "postgres_user",
        "password": "postgres_password",
    },
    "redis": {
        "url": "redis_url",
    },
    "circuit_breaker": {
        "failure_threshold": "circuit_breaker_failure_threshold",
        "cooldown_seconds": "circuit_breaker_cooldown_seconds",
        "half_open_max_requests": "circuit_breaker_half_open_max_requests",
    },
    "rate_limit": {
        "global_rps": "rate_limit_global_rps",
        "per_key_rps": "rate_limit_per_key_rps",
        "per_model_rps": "rate_limit_per_model_rps",
    },
    "logging": {
        "level": "log_level",
        "file": "log_file",
    },
}

ENV_OVERRIDE_KEYS: set[str] = {key.upper() for key in CONFIG_META}


class Settings(BaseModel):
    app_name: str = "UniuLink"
    app_env: str = "production"
    encryption_key: str = ""
    admin_api_key: str = "admin-secret-key-change-me"
    admin_hmac_ttl_seconds: int = 300
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "uniulink"
    postgres_user: str = "uniulink"
    postgres_password: str = "uniulink-secret-password"
    redis_url: str = "redis://localhost:6379/0"
    default_channel_timeout: int = 30
    default_max_retries: int = 2
    health_check_interval: int = 30
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_cooldown_seconds: int = 60
    circuit_breaker_half_open_max_requests: int = 3
    rate_limit_global_rps: int = 1000
    rate_limit_per_key_rps: int = 100
    rate_limit_per_model_rps: int = 200
    log_level: str = "INFO"
    log_file: str = ""
    raw_json_log: bool = False
    log_body: bool = False
    log_content: bool = False

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def _cast_value(key: str, value: Any) -> Any:
    if key not in CONFIG_META:
        return value
    typ = CONFIG_META[key][0]

    if isinstance(value, typ):
        return value

    if typ is bool:
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "on", "debug", "development", "dev"}
        return bool(value)

    if typ is int:
        return int(value)

    return str(value)


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env_vars: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            env_vars[key.strip()] = val.strip()
    return env_vars


def _load_from_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    flat: dict[str, Any] = {}
    for section, keys in YAML_SECTION_MAP.items():
        section_data = data.get(section, {})
        for key in keys:
            if key in section_data:
                flat[key] = section_data[key]
        for yaml_key, canonical_key in YAML_KEY_ALIASES.get(section, {}).items():
            if yaml_key in section_data:
                flat[canonical_key] = section_data[yaml_key]
    return flat


def _load_settings() -> Settings:
    raw: dict[str, Any] = {}

    yaml_data = _load_from_yaml(YAML_CONFIG_PATH)
    raw.update(yaml_data)

    env_data: dict[str, Any] = {}
    env_file_data = _parse_env_file(ENV_CONFIG_PATH)
    for k, v in env_file_data.items():
        upper = k.upper()
        lower_key = k.lower()
        if lower_key in CONFIG_META:
            env_data[lower_key] = _cast_value(lower_key, v)
        elif upper in ENV_OVERRIDE_KEYS:
            matched = next((ck for ck in CONFIG_META if ck.upper() == upper), None)
            if matched:
                env_data[matched] = _cast_value(matched, v)

    for k in CONFIG_META:
        env_val = os.environ.get(k.upper()) or os.environ.get(k.lower())
        if env_val is not None:
            env_data[k] = _cast_value(k, env_val)

    raw.update(env_data)

    kwargs: dict[str, Any] = {}
    for key in CONFIG_META:
        _, default, _, _ = CONFIG_META[key]
        kwargs[key] = raw.get(key, default)

    return Settings(**kwargs)


class ConfigManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._settings = _load_settings()
        self._yaml_path = YAML_CONFIG_PATH
        # 需要重启才能生效的配置项：只落盘、不改动运行中的 Settings，
        # 待下次重启（或 /config/reload）后生效。界面据此展示“待重启”标记。
        self._pending: dict[str, Any] = {}

    @property
    def settings(self) -> Settings:
        return self._settings

    def reload(self) -> Settings:
        with self._lock:
            self._settings = _load_settings()
            # 配置文件里的值此刻已成为“当前值”，待生效标记随之失效。
            self._pending.clear()
        return self._settings

    def get(self, key: str) -> Any:
        return getattr(self._settings, key, None)

    def effective_value(self, key: str) -> Any:
        """返回界面应展示的值：待重启项展示已写入文件的待生效值。"""
        with self._lock:
            if key in self._pending:
                return self._pending[key]
        return getattr(self._settings, key, None)

    def update(self, key: str, value: Any) -> dict[str, Any]:
        """更新配置项。

        热重载项立即生效并写入配置文件；需要重启的项只写入配置文件并记录为
        待生效，避免界面显示已生效而实际仍在使用旧值。两者的落盘结果都会如实
        返回，写入失败时抛出 ValueError，不伪装成功。
        """
        if key not in CONFIG_META:
            raise KeyError(f"Unknown config key: {key}")

        _, _, hot_reloadable, _ = CONFIG_META[key]
        casted = _cast_value(key, value)

        if not hot_reloadable:
            persisted, persist_error = self._persist_to_yaml(key, casted)
            if not persisted:
                raise ValueError(f"'{key}' 需要重启才能生效，但无法写入配置文件：{persist_error}")
            with self._lock:
                # 写回与当前运行值相同的值时无需重启，不残留待生效标记。
                if casted == getattr(self._settings, key, None):
                    self._pending.pop(key, None)
                else:
                    self._pending[key] = casted
            return {
                "key": key,
                "value": casted,
                "hot_reloadable": False,
                "restart_required": True,
                "persisted": True,
                "persist_error": "",
            }

        with self._lock:
            setattr(self._settings, key, casted)
            self._pending.pop(key, None)

        persisted, persist_error = self._persist_to_yaml(key, casted)
        return {
            "key": key,
            "value": casted,
            "hot_reloadable": True,
            "restart_required": False,
            "persisted": persisted,
            "persist_error": persist_error,
        }

    def _persist_to_yaml(self, key: str, value: Any) -> tuple[bool, str]:
        """把单个配置项写回 config.yaml，返回 (是否成功, 失败原因)。"""
        section = next(
            (sec for sec, keys in YAML_SECTION_MAP.items() if key in keys), None
        )
        if section is None:
            return False, f"'{key}' 未映射到配置文件的任何节点"

        if not self._yaml_path.exists():
            return False, f"未找到配置文件 {self._yaml_path}"

        try:
            with open(self._yaml_path) as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                return False, f"{self._yaml_path} 的顶层结构不是映射"
            section_data = data.get(section)
            if not isinstance(section_data, dict):
                section_data = {}
                data[section] = section_data

            # _load_from_yaml 里短别名会覆盖同名规范字段，因此若该节点已经在用别名，
            # 必须写别名；否则写规范名会在重启后被别名盖掉，改动看似保存却不生效。
            yaml_key = next(
                (
                    alias
                    for alias, canonical in YAML_KEY_ALIASES.get(section, {}).items()
                    if canonical == key and alias in section_data
                ),
                key,
            )
            section_data[yaml_key] = value
            # 别名与规范名同时存在时以别名生效，清掉会被忽略的重复项避免误导。
            if yaml_key != key and key in section_data:
                section_data.pop(key)

            # 保持原文件权限，就地写入（绑定挂载的单文件无法用 os.replace 替换）。
            with open(self._yaml_path, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        except yaml.YAMLError as exc:
            return False, f"{self._yaml_path} 不是合法的 YAML：{exc}"
        except OSError as exc:
            return False, f"写入 {self._yaml_path} 失败：{exc}"
        return True, ""

    def to_dict(self, mask_sensitive: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {}
        with self._lock:
            pending = dict(self._pending)
        for key in CONFIG_META:
            _, default, hot_reloadable, description = CONFIG_META[key]
            is_pending = key in pending
            value = pending[key] if is_pending else getattr(self._settings, key, default)
            if mask_sensitive and key in SENSITIVE_KEYS and value:
                value = mask_value(str(value))
            result[key] = {
                "value": value,
                "type": type(value).__name__,
                "default": default,
                "hot_reloadable": hot_reloadable,
                "description": description,
                "sensitive": key in SENSITIVE_KEYS,
                "pending_restart": is_pending,
            }
        return result

    def get_flat_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in CONFIG_META:
            _, default, _, _ = CONFIG_META[key]
            result[key] = getattr(self._settings, key, default)
        return result


def mask_value(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


config_manager = ConfigManager()
settings = config_manager.settings
