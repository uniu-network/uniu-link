"""CLIProxyAPI 托管实例与账号池的管理接口。

挂在 ``/api/admin/cpa`` 下，自动继承 ``AdminAuthMiddleware`` 的 HMAC 鉴权。

托管实例是单例：不需要（也不允许）在界面上增删实例，后端按需自动创建并维护。
托管渠道按账号类型拆分，名称为 ``CliProxyAPI-<账号类型>``。
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.logging import get_logger
from app.core.response import success_response
from app.models.channel import Channel
from app.models.cpa_instance import CpaInstance
from app.services import cpa_accounts, cpa_manager, cpa_quota
from app.services.health_checker import set_channel_health_status

logger = get_logger(__name__)
cpa_admin_router = APIRouter()

MAX_UPLOAD_BYTES = 1024 * 1024


class CpaAccountStatusRequest(BaseModel):
    name: str
    auth_index: Optional[str] = None
    disabled: bool


class CpaAccountBatchRequest(BaseModel):
    action: str
    names: list[str]


class CpaAccountRefreshRequest(BaseModel):
    name: str = ""
    all: bool = False


class CpaOAuthStartRequest(BaseModel):
    provider: str


class CpaAccountImportRequest(BaseModel):
    content: str
    name: str = ""
    filename: str = ""


async def _managed_channels(instance: CpaInstance) -> list[Channel]:
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(Channel)
            .where(Channel.cpa_instance_id == instance.id)
            .order_by(Channel.name)
        )
        return list(rows.scalars().all())


async def _instance_payload(instance: CpaInstance) -> dict[str, Any]:
    status = await cpa_manager.runtime_status(instance)
    payload = cpa_manager.serialize_instance(instance, status=status)
    payload["channels"] = [
        {
            "id": channel.id,
            "name": channel.name,
            "cpa_provider": channel.cpa_provider or "",
            "health_status": channel.health_status,
            "upstream_models": channel.upstream_models or [],
        }
        for channel in await _managed_channels(instance)
    ]
    return payload


async def _instance(db: AsyncSession) -> CpaInstance:
    """取得托管的单实例，不存在时按默认配置创建。"""
    return await cpa_manager.get_or_create_instance(db)


def _require_management() -> None:
    if not settings.cpa_manage_enabled:
        raise HTTPException(
            status_code=400,
            detail="托管 CLIProxyAPI 已禁用，请先在系统配置中开启 cpa_manage_enabled",
        )


async def _quota_snapshot(instance: CpaInstance, *, refresh: bool = False) -> dict[str, Any]:
    """额度快照：插件状态 + 按 ``auth_index`` 索引的账号额度。"""
    empty: dict[str, Any] = {"accounts": {}, "summary": {}, "generated_at": ""}
    if await cpa_manager.runtime_status(instance) != "running":
        return {
            **empty,
            "available": False,
            "reason": "实例未运行，无法读取账号额度",
            "plugin": {"installed": False, "available": False},
        }

    plugin = await cpa_quota.plugin_state(instance)
    if not plugin.get("available"):
        return {
            **empty,
            "available": False,
            "reason": plugin.get("reason") or "配额插件不可用",
            "plugin": plugin,
        }

    snapshot = await cpa_quota.fetch_quotas(instance, refresh=refresh)
    snapshot["plugin"] = plugin
    return snapshot


@cpa_admin_router.get("/status")
async def cpa_status():
    """返回托管能力与运行环境信息，供界面判断是否可安装。"""
    asset = ""
    try:
        asset = cpa_manager.platform_asset_name("x.y.z")
    except Exception:
        asset = ""

    return success_response(detail_result={
        "manage_enabled": settings.cpa_manage_enabled,
        "install_dir": str(cpa_manager.install_root()),
        "release_repo": settings.cpa_release_repo,
        "platform": platform.system().lower(),
        "machine": platform.machine().lower(),
        "asset_example": asset,
        "channel_prefix": cpa_manager.CPA_CHANNEL_PREFIX,
        "oauth_providers": [
            {"value": key, "label": cpa_accounts.provider_label(key)}
            for key in cpa_accounts.OAUTH_PROVIDERS
        ],
    })


@cpa_admin_router.get("/instance")
async def get_cpa_instance(db: AsyncSession = Depends(get_db)):
    """返回托管单实例的状态与已按账号类型拆分的托管渠道。"""
    return success_response(detail_result=await _instance_payload(await _instance(db)))


@cpa_admin_router.post("/instance/install")
async def install_cpa_binary(
    version: str = "",
    db: AsyncSession = Depends(get_db),
):
    _require_management()
    instance = await _instance(db)
    try:
        await cpa_manager.install_binary(instance, version)
    except cpa_manager.CpaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    instance.managed_binary = True
    instance.last_error = ""
    await db.commit()
    return success_response(detail_result=await _instance_payload(instance))


@cpa_admin_router.post("/instance/start")
async def start_cpa_instance(db: AsyncSession = Depends(get_db)):
    instance = await _instance(db)
    try:
        await cpa_manager.start_instance(instance)
    except cpa_manager.CpaError as exc:
        instance.status = "error"
        instance.last_error = str(exc)[:500]
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    instance.status = "running"
    instance.last_error = ""
    instance.last_started_at = datetime.now(timezone.utc)
    await db.commit()

    # 实例起来后确保配额插件在位；安装走后台，接口不为此阻塞。
    cpa_manager.schedule_quota_plugin_setup(instance)

    try:
        await cpa_manager.sync_managed_channels(instance)
    except Exception as exc:
        logger.error(f"同步托管渠道失败：{exc}")

    return success_response(detail_result=await _instance_payload(instance))


@cpa_admin_router.post("/instance/stop")
async def stop_cpa_instance(db: AsyncSession = Depends(get_db)):
    instance = await _instance(db)
    try:
        await cpa_manager.stop_instance(instance)
    except cpa_manager.CpaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    instance.status = "stopped"
    instance.pid = None
    await db.commit()

    # 进程已停止，托管渠道立即标记为不健康，避免继续路由到不可用实例。
    for channel in await _managed_channels(instance):
        await set_channel_health_status(channel.id, "unhealthy")

    return success_response(detail_result=await _instance_payload(instance))


@cpa_admin_router.post("/instance/restart")
async def restart_cpa_instance(db: AsyncSession = Depends(get_db)):
    instance = await _instance(db)
    try:
        await cpa_manager.restart_instance(instance)
    except cpa_manager.CpaError as exc:
        instance.status = "error"
        instance.last_error = str(exc)[:500]
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    instance.status = "running"
    instance.last_error = ""
    instance.last_started_at = datetime.now(timezone.utc)
    await db.commit()

    # 实例起来后确保配额插件在位；安装走后台，接口不为此阻塞。
    cpa_manager.schedule_quota_plugin_setup(instance)

    try:
        await cpa_manager.sync_managed_channels(instance)
    except Exception as exc:
        logger.error(f"同步托管渠道失败：{exc}")

    return success_response(detail_result=await _instance_payload(instance))


@cpa_admin_router.post("/instance/sync-channels")
async def sync_cpa_channels(db: AsyncSession = Depends(get_db)):
    """按账号类型重新同步托管渠道的模型列表与连接信息。"""
    instance = await _instance(db)
    try:
        channel_ids = await cpa_manager.sync_managed_channels(instance)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"同步托管渠道失败：{exc}") from exc

    healthy = await cpa_manager.is_instance_running(instance)
    for channel_id in channel_ids:
        await set_channel_health_status(channel_id, "healthy" if healthy else "unhealthy")

    channels = await _managed_channels(instance)
    return success_response(detail_result={
        "data": [
            {"id": channel.id, "name": channel.name, "cpa_provider": channel.cpa_provider or ""}
            for channel in channels
        ],
        "total": len(channels),
    })


@cpa_admin_router.get("/accounts")
async def list_cpa_accounts(db: AsyncSession = Depends(get_db)):
    instance = await _instance(db)
    try:
        files = await cpa_accounts.list_auth_files(instance)
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    moment = datetime.now(timezone.utc)
    accounts = [cpa_accounts.serialize_account(entry, moment) for entry in files]
    summary = cpa_accounts.summarize_accounts(files, moment)
    return success_response(detail_result={
        "data": accounts,
        "summary": summary,
        "by_provider": list(cpa_accounts.summarize_by_provider(files, moment).values()),
        "instance": {
            "id": instance.id,
            "name": instance.name,
            "status": await cpa_manager.runtime_status(instance),
            "quota_enabled": settings.cpa_quota_plugin_enabled,
        },
    })


@cpa_admin_router.get("/accounts/quota")
async def get_cpa_account_quotas(db: AsyncSession = Depends(get_db)):
    """各账号的剩余额度、套餐与重置时间，由配额插件提供。"""
    instance = await _instance(db)
    return success_response(detail_result=await _quota_snapshot(instance))


@cpa_admin_router.post("/accounts/quota/refresh")
async def refresh_cpa_account_quotas(db: AsyncSession = Depends(get_db)):
    """强制刷新额度快照（绕过插件的 30 分钟缓存）。"""
    instance = await _instance(db)
    return success_response(detail_result=await _quota_snapshot(instance, refresh=True))


@cpa_admin_router.post("/accounts/quota/install")
async def install_cpa_quota_plugin(db: AsyncSession = Depends(get_db)):
    """安装并确认配额插件（幂等）。"""
    instance = await _instance(db)
    if await cpa_manager.runtime_status(instance) != "running":
        raise HTTPException(status_code=409, detail="实例未运行，无法安装配额插件")
    plugin = await cpa_quota.ensure_plugin(instance)
    if not plugin.get("installed"):
        raise HTTPException(
            status_code=502, detail=plugin.get("reason") or "配额插件安装失败"
        )
    return success_response(detail_result=plugin)


@cpa_admin_router.patch("/accounts")
async def set_cpa_account_status(
    data: CpaAccountStatusRequest,
    db: AsyncSession = Depends(get_db),
):
    instance = await _instance(db)
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="账号名称不能为空")
    try:
        await cpa_accounts.patch_auth_file_status(
            instance, data.name.strip(), data.disabled, data.auth_index
        )
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result={"name": data.name, "disabled": data.disabled})


@cpa_admin_router.delete("/accounts")
async def delete_cpa_account(
    name: str,
    db: AsyncSession = Depends(get_db),
):
    instance = await _instance(db)
    if not name.strip():
        raise HTTPException(status_code=400, detail="账号名称不能为空")
    try:
        await cpa_accounts.delete_auth_file(instance, name.strip())
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result={"message": "账号已删除", "name": name})


@cpa_admin_router.get("/accounts/export")
async def export_cpa_account(
    name: str,
    db: AsyncSession = Depends(get_db),
):
    """以 JSON 文本导出凭据内容。

    管理接口的 HMAC 签名基于原始请求体，multipart 传输会破坏校验，
    因此把内容放进标准响应，由前端自行触发文件下载。
    """
    instance = await _instance(db)
    if not name.strip():
        raise HTTPException(status_code=400, detail="账号名称不能为空")
    try:
        content = await cpa_accounts.download_auth_file(instance, name.strip())
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=502, detail="凭据文件不是 UTF-8 文本") from exc

    return success_response(detail_result={"name": name.strip(), "content": text})


@cpa_admin_router.post("/accounts/import")
async def import_cpa_account(
    data: CpaAccountImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """导入凭据 JSON（粘贴内容，或由前端读取文件后转成文本）。"""
    instance = await _instance(db)
    content = data.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="凭据内容不能为空")
    if len(content.encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="凭据文件过大")

    import json as _json

    try:
        parsed = _json.loads(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="凭据内容不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="凭据内容必须是 JSON 对象")

    try:
        await cpa_accounts.upload_auth_file(
            instance,
            data.filename.strip() or "auth.json",
            content.encode("utf-8"),
            data.name.strip() or None,
        )
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result={"message": "账号已导入"})


@cpa_admin_router.post("/accounts/refresh")
async def refresh_cpa_accounts(
    data: CpaAccountRefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    instance = await _instance(db)
    try:
        result = await cpa_accounts.refresh_auth_files(
            instance, data.name.strip() or None, data.all
        )
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result=result)


@cpa_admin_router.post("/accounts/reset-quota")
async def reset_cpa_account_quota(
    data: CpaAccountRefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    instance = await _instance(db)
    try:
        result = await cpa_accounts.reset_quota(instance, data.name.strip() or None)
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result=result)


@cpa_admin_router.post("/accounts/batch")
async def batch_cpa_accounts(
    data: CpaAccountBatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量启用、禁用、删除或刷新账号。"""
    instance = await _instance(db)
    action = data.action.strip().lower()
    names = [name.strip() for name in data.names if name and name.strip()]
    if action not in {"enable", "disable", "delete", "refresh"}:
        raise HTTPException(status_code=400, detail="action must be enable, disable, delete or refresh")
    if not names:
        raise HTTPException(status_code=400, detail="names 不能为空")

    succeeded: list[str] = []
    failed: list[dict[str, str]] = []
    for name in names:
        try:
            if action == "enable":
                await cpa_accounts.patch_auth_file_status(instance, name, False)
            elif action == "disable":
                await cpa_accounts.patch_auth_file_status(instance, name, True)
            elif action == "delete":
                await cpa_accounts.delete_auth_file(instance, name)
            else:
                await cpa_accounts.refresh_auth_files(instance, name)
            succeeded.append(name)
        except cpa_accounts.CpaManagementError as exc:
            failed.append({"name": name, "error": str(exc)[:200]})

    return success_response(detail_result={
        "action": action,
        "succeeded": succeeded,
        "failed": failed,
    })


@cpa_admin_router.post("/oauth/start")
async def start_cpa_oauth(
    data: CpaOAuthStartRequest,
    db: AsyncSession = Depends(get_db),
):
    instance = await _instance(db)
    try:
        payload = await cpa_accounts.start_oauth(instance, data.provider)
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result=payload)


@cpa_admin_router.get("/oauth/status")
async def poll_cpa_oauth(
    state: str,
    db: AsyncSession = Depends(get_db),
):
    instance = await _instance(db)
    try:
        payload = await cpa_accounts.poll_oauth_status(instance, state)
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result=payload)


@cpa_admin_router.delete("/oauth/status")
async def cancel_cpa_oauth(
    state: str,
    db: AsyncSession = Depends(get_db),
):
    instance = await _instance(db)
    try:
        await cpa_accounts.cancel_oauth(instance, state)
    except cpa_accounts.CpaManagementError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return success_response(detail_result={"message": "登录会话已取消"})


@cpa_admin_router.get("/models")
async def list_cpa_models(db: AsyncSession = Depends(get_db)):
    instance = await _instance(db)
    if not await cpa_manager.is_instance_running(instance):
        raise HTTPException(status_code=409, detail="实例未运行，无法读取模型列表")
    models = await cpa_manager.fetch_available_models(instance)
    return success_response(detail_result={"data": models, "total": len(models)})
