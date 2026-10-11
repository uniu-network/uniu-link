"""CLIProxyAPI 账号池（auth files）的状态判定与管理接口客户端。

管理接口位于 CPA 的 ``/v0/management``，使用 ``Authorization: Bearer <management key>``。
由于托管实例由本进程在 127.0.0.1 上拉起，CPA 可以保持 ``allow-remote: false``。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.cpa_manager import (
    CpaError,
    management_base_url,
    management_key,
)

logger = get_logger(__name__)

MANAGEMENT_TIMEOUT = httpx.Timeout(20.0)

# OAuth 登录入口：CPA 账号类型 -> 管理接口路径。
# 该列表须与 CPA 注册的 *-auth-url 端点一致；缺少端点会返回 404。
OAUTH_PROVIDERS: dict[str, str] = {
    "claude": "anthropic-auth-url",
    "codex": "codex-auth-url",
    "antigravity": "antigravity-auth-url",
    "kimi": "kimi-auth-url",
    "kimi-ai": "kimi-ai-auth-url",
    "xai": "xai-auth-url",
    "devin": "devin-auth-url",
    "meta": "meta-auth-url",
}

PROVIDER_LABELS: dict[str, str] = {
    "claude": "Claude Code",
    "codex": "OpenAI Codex",
    "antigravity": "Antigravity",
    "kimi": "Kimi",
    "kimi-ai": "Kimi AI",
    "xai": "xAI",
    "devin": "Devin",
    "meta": "Meta",
    "gemini-cli": "Gemini CLI",
    "gemini": "Gemini",
    "vertex": "Vertex AI",
    "aistudio": "AI Studio",
    "qwen": "Qwen",
    "iflow": "iFlow",
    "openai-compatibility": "OpenAI 兼容",
}

_TIMESTAMP_RE = re.compile(
    r"^(?P<body>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>[Zz]|[+-]\d{2}:?\d{2})?$"
)

# 凭据级冷却作用域：这些冷却会让账号整体不可调度。
# 按模型的冷却不影响账号整体可用性，因此不在此列。
CREDENTIAL_COOLDOWN_SCOPES = {"auth", "credential"}


class CpaManagementError(CpaError):
    """管理接口返回错误。"""


def provider_label(provider: str) -> str:
    key = (provider or "").strip().lower()
    return PROVIDER_LABELS.get(key, provider or "未知类型")


def parse_timestamp(value: Any) -> datetime | None:
    """解析 CPA 返回的时间戳，统一为带时区的 UTC datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        match = _TIMESTAMP_RE.match(text)
        if match:
            fraction = (match.group("frac") or "")[:6]
            zone = match.group("tz") or ""
            if zone in ("Z", "z"):
                zone = "+00:00"
            elif zone and ":" not in zone:
                zone = f"{zone[:3]}:{zone[3:]}"
            text = match.group("body")
            if fraction:
                text += f".{fraction}"
            text += zone
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def active_cooldowns(entry: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """返回当前仍在生效的冷却项（含按模型的冷却）。"""
    moment = now or datetime.now(timezone.utc)
    active: list[dict[str, Any]] = []
    for cooldown in entry.get("cooldowns") or []:
        if not isinstance(cooldown, dict):
            continue
        remaining = cooldown.get("remaining_seconds")
        retry_at = parse_timestamp(cooldown.get("retry_at"))
        if isinstance(remaining, (int, float)) and remaining > 0:
            active.append(cooldown)
        elif retry_at is not None and retry_at > moment:
            active.append(cooldown)
    return active


def account_is_available(entry: dict[str, Any], now: datetime | None = None) -> bool:
    """判断账号当前是否可被 CPA 调度。

    只依据凭据级的禁用与冷却状态，与 CPA selector 的可用性过滤保持一致。
    「部分模型冷却」不算整体不可用，因为 CPA 仍会用它服务其它模型。
    """
    moment = now or datetime.now(timezone.utc)

    if entry.get("disabled") is True:
        return False
    if str(entry.get("status") or "").strip().lower() == "disabled":
        return False
    if entry.get("unavailable") is True:
        return False

    retry_at = parse_timestamp(entry.get("next_retry_after"))
    if retry_at is not None and retry_at > moment:
        return False

    for cooldown in active_cooldowns(entry, moment):
        scope = str(cooldown.get("scope") or "").strip().lower()
        if scope in CREDENTIAL_COOLDOWN_SCOPES:
            return False

    return True


def account_state(entry: dict[str, Any], now: datetime | None = None) -> str:
    """把 CPA 账号归一为界面使用的单一状态。"""
    moment = now or datetime.now(timezone.utc)
    status = str(entry.get("status") or "").strip().lower()

    if entry.get("disabled") is True or status == "disabled":
        return "disabled"
    if status == "pending":
        return "pending"
    if status == "refreshing":
        return "refreshing"
    if account_is_available(entry, moment):
        cooldowns = active_cooldowns(entry, moment)
        return "degraded" if cooldowns else "active"

    # 有明确恢复时间的属于冷却；否则视为需要人工处理的异常。
    retry_at = parse_timestamp(entry.get("next_retry_after"))
    if active_cooldowns(entry, moment) or (retry_at is not None and retry_at > moment):
        return "cooling"
    return "error"


def summarize_accounts(
    files: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """汇总账号池，供渠道健康判定与界面展示使用。"""
    moment = now or datetime.now(timezone.utc)
    counts = {
        "total": 0,
        "active": 0,
        "available": 0,
        "degraded": 0,
        "cooling": 0,
        "error": 0,
        "disabled": 0,
        "pending": 0,
        "refreshing": 0,
    }
    for entry in files:
        if not isinstance(entry, dict):
            continue
        counts["total"] += 1
        state = account_state(entry, moment)
        counts[state] = counts.get(state, 0) + 1
        if account_is_available(entry, moment):
            counts["available"] += 1

    return {
        **counts,
        # 只要池中还有账号可被调度，就认为该渠道健康。
        "healthy": counts["available"] > 0,
    }


def account_provider(entry: dict[str, Any]) -> str:
    """账号条目归一后的账号类型键，用于按类型拆分渠道。"""
    return str(entry.get("provider") or entry.get("type") or "").strip().lower()


def summarize_by_provider(
    files: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """按账号类型分组汇总，每个类型复用与整池一致的统计口径。"""
    moment = now or datetime.now(timezone.utc)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in files:
        if not isinstance(entry, dict):
            continue
        grouped.setdefault(account_provider(entry), []).append(entry)

    return {
        provider: {
            "provider": provider,
            "label": provider_label(provider),
            **summarize_accounts(entries, moment),
        }
        for provider, entries in grouped.items()
    }


def _headers(instance) -> dict[str, str]:
    key = management_key(instance)
    if not key:
        raise CpaManagementError("实例缺少管理密钥，无法访问管理接口")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


async def _request(
    instance,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    files: Any = None,
    data: Any = None,
) -> httpx.Response:
    url = f"{management_base_url(instance)}{path}"
    try:
        async with httpx.AsyncClient(timeout=MANAGEMENT_TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                files=files,
                data=data,
                headers=_headers(instance),
            )
    except httpx.HTTPError as exc:
        raise CpaManagementError(f"连接 CLIProxyAPI 管理接口失败：{exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:300]
        raise CpaManagementError(
            f"CLIProxyAPI 管理接口返回 HTTP {response.status_code}：{detail}"
        )
    return response


async def _json(instance, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = await _request(instance, method, path, **kwargs)
    try:
        payload = response.json()
    except ValueError as exc:
        raise CpaManagementError("CLIProxyAPI 管理接口返回了非 JSON 内容") from exc
    return payload if isinstance(payload, dict) else {"data": payload}


async def management_call(
    instance,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
) -> dict[str, Any]:
    """调用 CPA 管理接口并返回 JSON。

    账号池之外的其它管理接口客户端（如配额插件）复用它，以便共用管理密钥
    鉴权与 ``CpaManagementError`` 错误映射。
    """
    return await _json(
        instance, method, path, params=params, json_body=json_body
    )


async def list_auth_files(instance) -> list[dict[str, Any]]:
    payload = await _json(instance, "GET", "/auth-files")
    files = payload.get("files")
    if not isinstance(files, list):
        return []
    return [entry for entry in files if isinstance(entry, dict)]


async def list_auth_file_models(instance, name: str) -> list[str]:
    """读取单个账号可用的模型 ID。

    CPA 返回的是对象列表（``{"id": ..., "display_name": ...}``），必须取 ``id``；
    只接受字符串会把整个列表过滤成空。
    """
    payload = await _json(instance, "GET", "/auth-files/models", params={"name": name})
    models = payload.get("models")
    if not isinstance(models, list):
        return []

    result: list[str] = []
    for item in models:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
            if isinstance(model_id, str) and model_id:
                result.append(model_id)
    return result


async def patch_auth_file_status(
    instance,
    name: str,
    disabled: bool,
    auth_index: str | None = None,
) -> None:
    body: dict[str, Any] = {"name": name, "disabled": disabled}
    if auth_index:
        body["auth_index"] = auth_index
    await _request(instance, "PATCH", "/auth-files/status", json_body=body)


async def patch_auth_file_fields(instance, name: str, fields: dict[str, Any]) -> None:
    await _request(
        instance,
        "PATCH",
        "/auth-files/fields",
        json_body={"name": name, "fields": fields},
    )


async def delete_auth_file(instance, name: str) -> None:
    await _request(instance, "DELETE", "/auth-files", params={"name": name})


async def download_auth_file(instance, name: str) -> bytes:
    response = await _request(instance, "GET", "/auth-files/download", params={"name": name})
    return response.content


async def upload_auth_file(
    instance,
    filename: str,
    content: bytes,
    name: str | None = None,
) -> None:
    params = {"name": name} if name else None
    await _request(
        instance,
        "POST",
        "/auth-files",
        params=params,
        files={"file": (filename, content, "application/json")},
    )


async def refresh_auth_files(
    instance,
    name: str | None = None,
    refresh_all: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if refresh_all:
        body["all"] = True
    elif name:
        body["name"] = name
    return await _json(instance, "POST", "/auth-files/refresh", json_body=body)


async def reset_quota(instance, name: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if name:
        body["name"] = name
    return await _json(instance, "POST", "/reset-quota", json_body=body)


async def start_oauth(instance, provider: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    path = OAUTH_PROVIDERS.get((provider or "").strip().lower())
    if not path:
        raise CpaManagementError(f"不支持通过管理接口登录的账号类型：{provider}")
    # is_webui 必须带上：CPA 只在识别为 Web UI 请求时才在固定回调端口
    # （Codex 1455 / Claude 54545 / Antigravity）启动回调转发器。缺少该参数时
    # 授权链接照常生成，但浏览器授权后重定向到 localhost:<端口> 会 ERR_CONNECTION_REFUSED。
    # 其它账号类型的处理器不读该参数，多传无副作用。
    query = dict(params or {})
    query["is_webui"] = "true"
    return await _json(instance, "GET", f"/{path}", params=query)


async def poll_oauth_status(instance, state: str) -> dict[str, Any]:
    return await _json(instance, "GET", "/get-auth-status", params={"state": state})


async def cancel_oauth(instance, state: str) -> None:
    await _request(instance, "DELETE", "/oauth-session", params={"state": state})


def serialize_account(entry: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """把 CPA 账号条目整理成前端直接可用的结构。"""
    moment = now or datetime.now(timezone.utc)
    cooldowns = active_cooldowns(entry, moment)
    next_retry = parse_timestamp(entry.get("next_retry_after"))
    provider = str(entry.get("provider") or entry.get("type") or "")

    return {
        "id": str(entry.get("id") or ""),
        "auth_index": str(entry.get("auth_index") or ""),
        "name": str(entry.get("name") or ""),
        "provider": provider,
        "provider_label": provider_label(provider),
        "label": str(entry.get("label") or ""),
        "email": str(entry.get("email") or ""),
        "account": str(entry.get("account") or ""),
        "account_type": str(entry.get("account_type") or ""),
        "project_id": str(entry.get("project_id") or ""),
        "note": str(entry.get("note") or ""),
        "priority": entry.get("priority"),
        "weight": entry.get("weight"),
        "status": str(entry.get("status") or ""),
        "status_message": str(entry.get("status_message") or ""),
        "state": account_state(entry, moment),
        "available": account_is_available(entry, moment),
        "disabled": bool(entry.get("disabled")),
        "unavailable": bool(entry.get("unavailable")),
        "runtime_only": bool(entry.get("runtime_only")),
        "success": int(entry.get("success") or 0),
        "failed": int(entry.get("failed") or 0),
        "recent_requests": entry.get("recent_requests") or [],
        "cooldowns": cooldowns,
        "next_retry_after": next_retry.isoformat() if next_retry else "",
        "last_refresh": str(entry.get("last_refresh") or ""),
        "updated_at": str(entry.get("updated_at") or entry.get("modtime") or ""),
        "created_at": str(entry.get("created_at") or ""),
        "size": int(entry.get("size") or 0),
        "supports_quota": bool(entry.get("supports_quota")),
    }


async def collect_pool_snapshot(instance) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """拉取账号列表并返回 (账号条目, 汇总)。"""
    files = await list_auth_files(instance)
    moment = datetime.now(timezone.utc)
    return files, summarize_accounts(files, moment)
