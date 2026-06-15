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
    "cache_default_ttl": (int, 3600, True, "缓存默认过期时间(秒)"),
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
    "cache": ["cache_default_ttl"],
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
    "cache": {
        "default_ttl": "cache_default_ttl",
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
    cache_default_ttl: int = 3600
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

    @property
    def settings(self) -> Settings:
        return self._settings

    def reload(self) -> Settings:
        with self._lock:
            self._settings = _load_settings()
        return self._settings

    def get(self, key: str) -> Any:
        return getattr(self._settings, key, None)

    def update(self, key: str, value: Any) -> bool:
        if key not in CONFIG_META:
            raise KeyError(f"Unknown config key: {key}")

        _, _, hot_reloadable, _ = CONFIG_META[key]
        if not hot_reloadable:
            raise ValueError(f"'{key}' is not hot-reloadable, restart required")

        casted = _cast_value(key, value)
        with self._lock:
            setattr(self._settings, key, casted)

        self._try_persist_to_yaml(key, casted)
        return True

    def _try_persist_to_yaml(self, key: str, value: Any) -> None:
        try:
            if not self._yaml_path.exists():
                return
            with open(self._yaml_path) as f:
                data = yaml.safe_load(f) or {}

            section = None
            for sec, keys in YAML_SECTION_MAP.items():
                if key in keys:
                    section = sec
                    break

            if section:
                if section not in data:
                    data[section] = {}
                data[section][key] = value

                with open(self._yaml_path, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        except Exception:
            pass

    def to_dict(self, mask_sensitive: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in CONFIG_META:
            _, default, hot_reloadable, description = CONFIG_META[key]
            value = getattr(self._settings, key, default)
            if mask_sensitive and key in SENSITIVE_KEYS and value:
                value = mask_value(str(value))
            result[key] = {
                "value": value,
                "type": type(value).__name__,
                "default": default,
                "hot_reloadable": hot_reloadable,
                "description": description,
                "sensitive": key in SENSITIVE_KEYS,
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
