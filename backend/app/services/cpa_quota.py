"""CLIProxyAPI 配额插件客户端与额度归一化。

托管实例会在启动后按需安装 ``cpa-quota-api-extension`` 插件，由它向上游查询
每个账号的额度窗口（Codex / Claude / Antigravity / Gemini CLI），并把结果暴露
在自己的管理路由 ``/v0/management/plugins/<id>/v1/quotas``。

该插件没有实现 CPA 原生的 ``QuotaProvider``，所以不能用
``/v0/management/quota/fetch``——未注册配额提供者时它固定返回 501。各家上游的
字段结构也不一致（``remaining_percent`` / ``remainingFraction`` / ``resets_at``
/ ``resetTime`` 混用），因此这里统一走防御式提取：递归找出所有形如额度窗口的
对象，再归一成 ``windows`` 列表供界面直接渲染。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger
from app.services import cpa_manager
from app.services.cpa_accounts import CpaManagementError, management_call
from app.services.cpa_manager import QUOTA_PLUGIN_ID

logger = get_logger(__name__)

# 插件自己的版本化只读接口前缀（相对 /v0/management）。
QUOTA_ROUTE_PREFIX = f"/plugins/{QUOTA_PLUGIN_ID}/v1"
# 一次取全量账号额度，插件的 limit 上限为 500。
QUOTA_LIST_LIMIT = 500
# 安装后 CPA 异步改写配置并重载插件，注册完成前访问插件路由会得到 404。
PLUGIN_LOAD_TIMEOUT = 30.0
PLUGIN_LOAD_POLL_INTERVAL = 0.5

# 窗口标识 -> 界面文案。
_WINDOW_LABELS: dict[str, str] = {
    "five_hour": "5 小时",
    "fivehour": "5 小时",
    "5h": "5 小时",
    "seven_day": "7 天",
    "sevenday": "7 天",
    "7d": "7 天",
    "primary": "主窗口",
    "secondary": "次窗口",
    "daily": "今日",
    "weekly": "本周",
    "monthly": "本月",
    "hourly": "每小时",
    "quota": "额度",
}

# 出现任一键即视为一个额度窗口，命中后不再向内递归。
_WINDOW_KEYS = frozenset(
    {
        "used_percent",
        "usedPercent",
        "percent_used",
        "remaining_percent",
        "remainingPercent",
        "remainingFraction",
        "remaining_fraction",
        "resets_at",
        "resetsAt",
        "reset_at",
        "resetAt",
        "reset_time",
        "resetTime",
        "window_seconds",
        "windowSeconds",
    }
)


def _first(node: dict[str, Any], *keys: str) -> Any:
    """返回第一个存在且非 None 的键值。"""
    for key in keys:
        if key in node and node[key] is not None:
            return node[key]
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _quota_percentages(node: dict[str, Any]) -> tuple[float | None, float | None]:
    """从窗口对象里取出已用/剩余百分比，缺一个就按 100 互补。"""
    used = _number(_first(node, "used_percent", "usedPercent", "percent_used"))
    remaining = _number(_first(node, "remaining_percent", "remainingPercent"))
    # remainingFraction 按定义是 0~1 的比例，与百分数字段区分处理。
    fraction = _number(_first(node, "remainingFraction", "remaining_fraction"))
    if remaining is None and fraction is not None:
        remaining = round(fraction * 100, 4)
    if remaining is None and used is not None:
        remaining = round(100.0 - used, 4)
    if used is None and remaining is not None:
        used = round(100.0 - remaining, 4)
    return used, remaining


def _reset_time(node: dict[str, Any]) -> str:
    value = _first(
        node, "resets_at", "resetsAt", "reset_at", "resetAt", "reset_time", "resetTime"
    )
    if isinstance(value, str):
        return value.strip()
    number = _number(value)
    if number is not None and number > 0:
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    return ""


def _collect_windows(node: Any, path: tuple[str, ...] = ()) -> list[tuple[str, dict[str, Any]]]:
    """递归收集额度窗口，返回 ``(路径, 窗口对象)`` 列表。"""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if _WINDOW_KEYS & set(node.keys()):
            found.append((".".join(path) or "quota", node))
            return found
        for key, value in node.items():
            found.extend(_collect_windows(value, path + (str(key),)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_collect_windows(value, path + (str(index),)))
    return found


def _window_label(path: str, node: dict[str, Any]) -> str:
    explicit = node.get("window")
    name = explicit.strip() if isinstance(explicit, str) else ""
    if not name:
        parts = [part for part in path.split(".") if part]
        while parts and parts[-1].isdigit():
            parts.pop()
        name = parts[-1] if parts else "quota"
    for suffix in ("_window", "Window", "_bucket", "Bucket"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return _WINDOW_LABELS.get(name) or _WINDOW_LABELS.get(name.lower()) or name or "额度"


def _plan(node: Any) -> str:
    """取套餐名；上游字段名不一致，因此递归查找第一个非空值。"""
    if isinstance(node, dict):
        value = _first(
            node,
            "plan_type",
            "planType",
            "chatgpt_plan_type",
            "plan",
            "tier_name",
            "tierName",
            "tier",
        )
        if isinstance(value, str) and value.strip():
            return value.strip()
        for child in node.values():
            found = _plan(child)
            if found:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _plan(child)
            if found:
                return found
    return ""


def _error_text(entry: dict[str, Any]) -> str:
    value = entry.get("error")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        message = _first(value, "message", "detail", "code")
        if isinstance(message, str):
            return message.strip()
    return ""


def _window_name(node: dict[str, Any]) -> str:
    """窗口对应的模型名（Antigravity 按模型给额度，同一配额由多个模型共享）。"""
    value = _first(node, "model", "model_id", "modelId", "model_name")
    return value.strip() if isinstance(value, str) else ""


def _group_label(models: list[str]) -> str:
    """多个模型共享同一配额时的分组名，例如 gemini-* → Gemini。"""
    if not models:
        return "额度"
    if len(models) == 1:
        return models[0]
    prefix = models[0].split("-")[0]
    if prefix and all(model.split("-")[0] == prefix for model in models):
        return prefix.capitalize()
    return f"{len(models)} 个模型"


def normalize_account(entry: dict[str, Any]) -> dict[str, Any]:
    """把一个账号条目归一成界面可直接渲染的额度结构。

    按模型给额度的来源（Antigravity）会把同一个配额重复写在每个模型上，这里按
    ``(剩余百分比, 重置时间)`` 合并，避免界面上出现几十行同值记录。
    """
    merged: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for path, node in _collect_windows(entry):
        used, remaining = _quota_percentages(node)
        resets_at = _reset_time(node)
        if used is None and remaining is None and not resets_at:
            continue
        model = _window_name(node)
        key = ("model", remaining, resets_at) if model else ("window", path)
        item = merged.get(key)
        if item is None:
            description = node.get("description")
            merged[key] = {
                "label": "" if model else _window_label(path, node),
                "models": [model] if model else [],
                "used_percent": used,
                "remaining_percent": remaining,
                "resets_at": resets_at,
                "description": description if isinstance(description, str) else "",
            }
            order.append(key)
        elif model and model not in merged[key]["models"]:
            merged[key]["models"].append(model)

    windows: list[dict[str, Any]] = []
    used_labels: set[str] = set()
    for key in order:
        item = merged[key]
        models = item["models"]
        label = _group_label(models) if models else item["label"]
        unique = label if label not in used_labels else f"{label}（{item['resets_at'] or item['remaining_percent']}）"
        used_labels.add(label)
        windows.append(
            {
                "key": unique,
                "label": label,
                "used_percent": item["used_percent"],
                "remaining_percent": item["remaining_percent"],
                "resets_at": item["resets_at"],
                "description": item["description"] or "、".join(models),
                "model_count": len(models),
            }
        )

    supported = entry.get("supported")
    state = _first(entry, "status", "credential_state")
    return {
        "supported": bool(supported) if supported is not None else bool(windows),
        "status": state if isinstance(state, str) else "",
        "plan": _plan(entry),
        "available": _bool_or_none(_first(entry, "available")),
        "exhausted": _bool_or_none(_first(entry, "exhausted")),
        "windows": windows,
        "error": _error_text(entry),
    }


async def plugin_state(instance) -> dict[str, Any]:
    """读取配额插件的安装与加载状态。"""
    try:
        payload = await management_call(instance, "GET", "/plugins")
    except CpaManagementError as exc:
        return {"installed": False, "available": False, "reason": str(exc)}

    plugins_enabled = bool(payload.get("plugins_enabled"))
    entries = payload.get("plugins")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id") != QUOTA_PLUGIN_ID:
                continue
            # CPA 只要配置里声明了 configs.<id> 就会列出该插件，甚至产物并不存在；
            # 因此安装状态以磁盘上的动态库为准，否则空环境会被误判成已安装。
            if not cpa_manager.quota_plugin_installed(instance):
                break
            metadata = entry.get("metadata")
            version = ""
            if isinstance(metadata, dict) and isinstance(metadata.get("version"), str):
                version = metadata["version"]
            registered = bool(entry.get("registered"))
            enabled = bool(entry.get("effective_enabled", entry.get("enabled")))
            return {
                "installed": True,
                "registered": registered,
                "enabled": enabled,
                "available": registered and enabled,
                "plugins_enabled": plugins_enabled,
                "version": version,
                "reason": "" if registered and enabled else "配额插件已安装但尚未加载",
            }

    reason = "配额插件尚未安装"
    if not plugins_enabled:
        reason = "实例配置未开启插件支持，重启实例后生效"
    return {
        "installed": False,
        "available": False,
        "plugins_enabled": plugins_enabled,
        "reason": reason,
    }


async def _wait_until_loaded(instance, timeout: float = PLUGIN_LOAD_TIMEOUT) -> dict[str, Any]:
    """等待插件完成注册：安装返回后 CPA 才会异步重载并注册它。"""
    deadline = time.monotonic() + timeout
    state = await plugin_state(instance)
    while not state.get("available"):
        if time.monotonic() >= deadline:
            return state
        await asyncio.sleep(PLUGIN_LOAD_POLL_INTERVAL)
        state = await plugin_state(instance)
    return state


async def ensure_plugin(instance) -> dict[str, Any]:
    """确保配额插件已安装并加载（幂等）；失败不抛错，由调用方按状态展示。"""
    state = await plugin_state(instance)
    if state.get("installed"):
        if state.get("available"):
            return state
        # 已安装但被判定为禁用（例如配置里缺 configs.<id>.enabled），先尝试重新启用。
        if state.get("enabled") is False:
            try:
                await management_call(
                    instance,
                    "PATCH",
                    f"/plugins/{QUOTA_PLUGIN_ID}/enabled",
                    json_body={"enabled": True},
                )
            except CpaManagementError as exc:
                logger.warning("启用配额插件失败：%s", exc)
        return await _wait_until_loaded(instance)
    if not state.get("plugins_enabled", True):
        return state

    try:
        # 插件商店按当前 GOOS/GOARCH 选择产物、校验 checksums 并解包到 plugins 目录，
        # 装好后由 CPA 热加载，不需要重启实例。
        await management_call(
            instance, "POST", f"/plugin-store/{QUOTA_PLUGIN_ID}/install", json_body={}
        )
    except CpaManagementError as exc:
        logger.warning("安装 CLIProxyAPI 配额插件失败：%s", exc)
        state["reason"] = f"安装配额插件失败：{exc}"
        return state

    loaded = await _wait_until_loaded(instance)
    if loaded.get("available"):
        logger.info("CLIProxyAPI 配额插件已安装：%s", QUOTA_PLUGIN_ID)
        return loaded
    loaded["reason"] = loaded.get("reason") or "配额插件安装后未被加载"
    logger.warning("配额插件不可用：%s", loaded.get("reason"))
    return loaded


async def fetch_quotas(instance, *, refresh: bool = False) -> dict[str, Any]:
    """读取账号额度快照，按 ``auth_index`` 建索引。"""
    params: dict[str, Any] = {"limit": QUOTA_LIST_LIMIT}
    if refresh:
        # 绕过插件缓存；插件自身会去重，不会产生并发重复刷新。
        params["refresh"] = "true"

    try:
        payload = await management_call(
            instance, "GET", f"{QUOTA_ROUTE_PREFIX}/quotas", params=params
        )
    except CpaManagementError as exc:
        return {"available": False, "reason": str(exc), "accounts": {}, "summary": {}}

    accounts: dict[str, dict[str, Any]] = {}
    raw_accounts = payload.get("accounts")
    if isinstance(raw_accounts, list):
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            index = _first(item, "auth_index", "authIndex")
            if not isinstance(index, str) or not index:
                continue
            accounts[index] = normalize_account(item)

    generated_at = payload.get("generated_at")
    summary = payload.get("summary")
    return {
        "available": True,
        "reason": "",
        "generated_at": generated_at if isinstance(generated_at, str) else "",
        "cached": bool(payload.get("cached")),
        "summary": summary if isinstance(summary, dict) else {},
        "accounts": accounts,
    }
