"""由 UniuLink 托管的 CLIProxyAPI（CPA）运行实例。

职责范围：二进制获取与校验、实例目录与配置生成、子进程生命周期、健康探测。

约定：数据库中的 ``pid``/``status`` 只是持久化快照，运行时状态一律以进程探测
与 ``/healthz`` 为准，不直接依赖 ORM 字段判断实例是否可用。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import secrets
import shutil
import signal
import socket
import tarfile
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.config import BACKEND_DIR, PROJECT_ROOT, settings
from app.core.encryption import key_encryption
from app.core.logging import get_logger

logger = get_logger(__name__)

BINARY_NAME = "CLIProxyAPI"
WINDOWS_BINARY_NAME = "CLIProxyAPI.exe"
# 官方 Release 压缩包内部的二进制名（与压缩包文件名 CLIProxyAPI_*.tar.gz 不同）。
ARCHIVE_BINARY_NAMES = {
    "cli-proxy-api",
    "cli-proxy-api.exe",
    "cliproxyapi",
    "cliproxyapi.exe",
}
BINARY_STORE_DIRNAME = "bin"
INSTANCE_DIRNAME = "instances"
# CPA 原生插件的存放目录名，位于实例安装目录之下。
PLUGIN_DIRNAME = "plugins"
# 默认安装的配额插件：提供账号额度百分比、套餐与重置时间。
QUOTA_PLUGIN_ID = "cpa-quota-api-extension"
# 未配置 cpa_install_dir 时的默认托管目录，位于 backend/ 之下。
DEFAULT_INSTALL_DIRNAME = ".uniulink"
# 托管实例固定为单例，创建时使用的名称。
SINGLETON_INSTANCE_NAME = "default"
DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=300.0)
HEALTH_PROBE_TIMEOUT = 5.0
STOP_POLL_INTERVAL = 0.2

# 本进程拉起的子进程句柄，用于回收与状态刷新；被接管的外部进程不在其中。
_processes: dict[str, asyncio.subprocess.Process] = {}
_reapers: dict[str, asyncio.Task[None]] = {}
# 后台维护任务（如配额插件安装）的强引用，避免被垃圾回收；关停时统一取消。
_background_tasks: set[asyncio.Task[None]] = set()


class CpaError(RuntimeError):
    """托管 CLIProxyAPI 实例时可预期的错误。"""


# --------------------------------------------------------------------------
# 目录与路径
# --------------------------------------------------------------------------


def _absolute(path_value: str | os.PathLike[str]) -> Path:
    """把配置中可能出现的相对路径按项目根目录解析为绝对路径。

    配置路径不应随进程工作目录变化，因此相对值统一以 ``PROJECT_ROOT`` 为基准。
    """
    path = Path(path_value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def instance_path(path_value: str | os.PathLike[str]) -> Path:
    """解析实例记录中的路径，并绝对化。

    ``create_subprocess_exec()`` 会先切换到 ``cwd`` 再解析可执行文件，所以相对
    路径会被解释成安装目录之下的路径，历史上确实产生过
    ``instances/<id>/.uniulink/...`` 这类嵌套目录。

    历史版本把相对路径直接写进了 ``cpa_instances``，当时的基准是进程工作目录，
    按文档即 ``backend/``。这里固定按 ``BACKEND_DIR`` 解析，结果不依赖当前工作
    目录，并指向这些实例文件实际所在的位置。
    """
    path = Path(path_value).expanduser()
    return path if path.is_absolute() else (BACKEND_DIR / path)


def install_root() -> Path:
    """托管文件根目录：默认 backend/.uniulink，无需手工配置。"""
    configured = (settings.cpa_install_dir or "").strip()
    if configured:
        return _absolute(configured)
    return BACKEND_DIR / DEFAULT_INSTALL_DIRNAME


def instance_install_dir(instance) -> Path:
    """实例安装目录的绝对路径，供落盘与删除复用。"""
    return instance_path(instance.install_dir)


def binary_store_dir(version: str) -> Path:
    return install_root() / BINARY_STORE_DIRNAME / (version or "local")


def default_instance_dir(instance_id: str) -> Path:
    if not instance_id:
        raise CpaError("实例尚未分配 ID，无法确定安装目录")
    return install_root() / INSTANCE_DIRNAME / instance_id


def ensure_manage_enabled() -> None:
    if not settings.cpa_manage_enabled:
        raise CpaError(
            "托管 CLIProxyAPI 已禁用，请先设置 cpa_manage_enabled 为 true"
        )


def ensure_instance_layout(instance) -> Path:
    base = instance_install_dir(instance)
    base.mkdir(parents=True, exist_ok=True)
    instance_path(instance.auth_dir).mkdir(parents=True, exist_ok=True)
    instance_path(instance.log_path).parent.mkdir(parents=True, exist_ok=True)
    if settings.cpa_quota_plugin_enabled:
        plugin_dir(instance).mkdir(parents=True, exist_ok=True)
    return base


def plugin_dir(instance) -> Path:
    """CPA 插件目录的绝对路径。

    CPA 的 ``plugins.dir`` 不写 ``~`` 时按进程工作目录解析，而托管实例以
    ``cwd=install_dir`` 运行，因此显式给出绝对路径，避免装到别处。
    """
    return instance_install_dir(instance) / PLUGIN_DIRNAME


def quota_plugin_installed(instance) -> bool:
    """配额插件产物是否已落盘。

    只有插件目录里真实存在动态库才算已安装：CPA 的 ``/plugins`` 会因为配置里
    声明了 ``configs.<id>.enabled`` 就列出该插件，据此判断会把空环境误判成
    「已安装」，从而跳过安装并一直等待加载。
    """
    directory = plugin_dir(instance)
    if not directory.is_dir():
        return False
    for suffix in (".so", ".dylib", ".dll"):
        if any(directory.rglob(f"{QUOTA_PLUGIN_ID}*{suffix}")):
            return True
    return False


def instance_base_url(instance) -> str:
    host = (instance.host or "127.0.0.1").strip()
    return f"http://{host}:{instance.port}"


def health_url(instance) -> str:
    return f"{instance_base_url(instance)}/healthz"


def management_base_url(instance) -> str:
    return f"{instance_base_url(instance)}/v0/management"


# --------------------------------------------------------------------------
# 端口与密钥
# --------------------------------------------------------------------------


def allocate_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def generate_key() -> str:
    return secrets.token_urlsafe(32)


def management_key(instance) -> str:
    return key_encryption.decrypt(instance.encrypted_management_key or "")


def access_key(instance) -> str:
    return key_encryption.decrypt(instance.encrypted_access_key or "")


# --------------------------------------------------------------------------
# 配置生成
# --------------------------------------------------------------------------


def build_config(instance) -> dict[str, Any]:
    """生成扁平布局的 CPA 配置。

    扁平键（``port``/``api-keys``/``auth-dir``/``remote-management``）在 CPA v8
    中仍被映射到新的分组键，同时兼容更早版本，因此比 v8 分组布局更适合由
    网关程序化生成。
    """
    config = {
        "host": instance.host or "127.0.0.1",
        "port": instance.port,
        # 必须写绝对路径：CPA 以 cwd=install_dir 运行，相对 auth-dir 会被它
        # 解析成 install_dir 之下的嵌套目录。
        "auth-dir": str(instance_path(instance.auth_dir)),
        "api-keys": [access_key(instance)],
        "remote-management": {
            "allow-remote": False,
            "secret-key": management_key(instance),
            # 由 UniuLink 提供管理界面，避免 CPA 自行下载控制面板。
            "disable-control-panel": True,
        },
        "debug": False,
        "request-log": False,
        "logging-to-file": False,
    }
    if settings.cpa_quota_plugin_enabled:
        # 原生插件是进程内动态库，必须开启 plugins.enabled 才会被加载；
        # 插件本体由后台任务按需安装（见 schedule_quota_plugin_setup）。
        plugins_block: dict[str, Any] = {
            "enabled": True,
            "dir": str(plugin_dir(instance)),
        }
        # configs.<id>.enabled 只在产物已存在时声明：CPA 会把缺失值归一成 false，
        # 不写它插件在下次启动后会变成禁用；但在空环境里预写又会被 /plugins 当成
        # 已安装。以磁盘产物为准可以同时满足两边。
        if quota_plugin_installed(instance):
            plugins_block["configs"] = {QUOTA_PLUGIN_ID: {"enabled": True}}
        config["plugins"] = plugins_block
    return config


def render_config_yaml(config: dict[str, Any]) -> str:
    header = (
        "# 该文件由 UniuLink 自动生成，手工修改会在实例重启时被覆盖。\n"
        "# This file is generated by UniuLink and overwritten when the instance restarts.\n"
    )
    return header + yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def write_config(instance) -> None:
    config_file = instance_path(instance.config_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    payload = render_config_yaml(build_config(instance))
    fd, tmp_name = tempfile.mkstemp(dir=str(config_file.parent), prefix=".config-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, config_file)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def initialize_instance(instance) -> None:
    """补齐路径、端口与密钥，并落盘初始配置。"""
    if not instance.id:
        instance.id = str(uuid.uuid4())
    if instance.install_dir:
        # 归一化为绝对路径：历史记录里可能存着依赖进程工作目录的相对路径。
        base = instance_path(instance.install_dir)
        instance.install_dir = str(base)
    else:
        base = default_instance_dir(instance.id)
        instance.install_dir = str(base)
    base.mkdir(parents=True, exist_ok=True)

    if not instance.config_path:
        instance.config_path = str(base / "config.yaml")
    if not instance.auth_dir:
        instance.auth_dir = str(base / "auths")
    if not instance.log_path:
        instance.log_path = str(base / "logs" / "cpa.log")
    if not instance.host:
        instance.host = "127.0.0.1"
    if not instance.port:
        instance.port = allocate_port(instance.host)
    if not instance.encrypted_management_key:
        instance.encrypted_management_key = key_encryption.encrypt(generate_key())
    if not instance.encrypted_access_key:
        instance.encrypted_access_key = key_encryption.encrypt(generate_key())

    ensure_instance_layout(instance)
    write_config(instance)


# --------------------------------------------------------------------------
# 二进制获取
# --------------------------------------------------------------------------


def platform_asset_name(version: str) -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(machine)
    if arch is None:
        raise CpaError(f"暂不支持的 CPU 架构：{machine}")
    if system not in {"linux", "darwin", "windows"}:
        raise CpaError(f"暂不支持的操作系统：{system}")
    if version.startswith("v"):
        version = version[1:]
    suffix = "zip" if system == "windows" else "tar.gz"
    return f"{BINARY_NAME}_{version}_{system}_{arch}.{suffix}"


def _api_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("api.github.com"):
        return base
    if "github.com" in base and base.startswith("https://github.com"):
        return "https://api.github.com"
    return f"{base}/api/v3"


def _release_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "UniuLink"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def resolve_latest_version() -> str:
    repo = settings.cpa_release_repo.strip()
    if not repo:
        raise CpaError("未配置 cpa_release_repo")
    url = f"{_api_base(settings.cpa_download_base_url)}/repos/{repo}/releases/latest"
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url, headers=_release_headers())
    if response.status_code >= 400:
        raise CpaError(
            f"获取 CLIProxyAPI 最新版本失败（HTTP {response.status_code}）：{response.text[:200]}"
        )
    tag = str(response.json().get("tag_name") or "").strip()
    if not tag:
        raise CpaError("CLIProxyAPI 发布信息缺少 tag_name")
    return tag


async def _download(client: httpx.AsyncClient, url: str, dest: Path) -> None:
    async with client.stream("GET", url) as response:
        if response.status_code >= 400:
            raise CpaError(f"下载失败（HTTP {response.status_code}）：{url}")
        with dest.open("wb") as handle:
            async for chunk in response.aiter_bytes():
                handle.write(chunk)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip().lower(), parts[1].strip().lstrip("*")
        if digest:
            checksums[name] = digest
    return checksums


def _extract_binary(archive: Path, destination: Path) -> None:
    """从官方 Release 压缩包中取出可执行文件。

    官方包里的二进制名是 ``cli-proxy-api``（Windows 为 ``cli-proxy-api.exe``），
    而压缩包文件名用的是 ``CLIProxyAPI``，两者不同，按后者搜索必然失败。
    """
    with tempfile.TemporaryDirectory(dir=str(destination.parent), prefix=".extract-") as tmp:
        tmp_dir = Path(tmp)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(tmp_dir)
        else:
            with tarfile.open(archive, "r:gz") as bundle:
                bundle.extractall(tmp_dir)

        files = [path for path in sorted(tmp_dir.rglob("*")) if path.is_file()]
        candidate = next(
            (path for path in files if path.name.lower() in ARCHIVE_BINARY_NAMES),
            None,
        )
        if candidate is None:
            names = ", ".join(path.name for path in files[:10]) or "(空)"
            raise CpaError(
                f"压缩包中未找到 CLIProxyAPI 可执行文件，实际包含：{names}"
            )

        shutil.move(str(candidate), str(destination))
        if os.name != "nt":
            destination.chmod(0o755)


async def install_binary(instance, version: str = "") -> str:
    """下载并校验指定版本，返回可执行文件路径。

    ``version`` 为空时取最新发布版本。已安装的版本直接复用，不重复下载。
    """
    ensure_manage_enabled()
    repo = settings.cpa_release_repo.strip()
    base_url = settings.cpa_download_base_url.rstrip("/")
    if not repo:
        raise CpaError("未配置 cpa_release_repo")

    tag = version.strip() or await resolve_latest_version()
    normalized = tag[1:] if tag.startswith("v") else tag
    asset = platform_asset_name(tag)
    target_dir = binary_store_dir(normalized)
    target = target_dir / (WINDOWS_BINARY_NAME if os.name == "nt" else BINARY_NAME)
    if target.exists():
        instance.binary_path = str(target)
        instance.version = normalized
        return str(target)

    target_dir.mkdir(parents=True, exist_ok=True)
    release_url = f"{base_url}/{repo}/releases/download/{tag}"
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            archive_path = tmp_dir / asset
            await _download(client, f"{release_url}/{asset}", archive_path)

            expected = None
            try:
                checksum_resp = await client.get(f"{release_url}/checksums.txt")
                if checksum_resp.status_code < 400:
                    expected = parse_checksums(checksum_resp.text).get(asset)
            except httpx.HTTPError as exc:
                logger.warning(f"获取 CLIProxyAPI 校验文件失败：{exc}")

            if not expected:
                raise CpaError(f"无法从 checksums.txt 获取 {asset} 的校验值，已中止安装")
            actual = _sha256_of(archive_path)
            if actual.lower() != expected.lower():
                raise CpaError(f"{asset} 校验失败：期望 {expected}，实际 {actual}")

            await asyncio.to_thread(_extract_binary, archive_path, target)

    instance.binary_path = str(target)
    instance.version = normalized
    logger.info(
        "CLIProxyAPI binary installed",
        extra={"instance": instance.name, "version": normalized, "path": str(target)},
    )
    return str(target)


def verify_local_binary(path: str) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise CpaError(f"本地二进制不存在：{candidate}")
    if os.name != "nt" and not os.access(candidate, os.X_OK):
        raise CpaError(f"本地二进制不可执行：{candidate}")
    return str(candidate.resolve())


# --------------------------------------------------------------------------
# 进程生命周期
# --------------------------------------------------------------------------


def pid_file(instance) -> Path:
    base = (instance.install_dir or "").strip()
    if not base:
        raise CpaError("实例尚未初始化安装目录")
    return instance_install_dir(instance) / "cpa.pid"


def read_pid(instance) -> int | None:
    path = pid_file(instance)
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(raw) if raw.isdigit() else None


def write_pid(instance, pid: int) -> None:
    try:
        pid_file(instance).write_text(str(pid), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"写入 CLIProxyAPI pid 文件失败：{exc}")


def clear_pid(instance) -> None:
    pid_file(instance).unlink(missing_ok=True)


def is_process_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def probe_health(instance) -> bool:
    try:
        async with httpx.AsyncClient(timeout=HEALTH_PROBE_TIMEOUT) as client:
            response = await client.get(health_url(instance))
    except httpx.HTTPError:
        return False
    return 200 <= response.status_code < 300


async def wait_until_healthy(instance, timeout: float | None = None) -> bool:
    deadline = asyncio.get_running_loop().time() + (
        timeout if timeout is not None else float(settings.cpa_start_timeout)
    )
    while asyncio.get_running_loop().time() < deadline:
        if await probe_health(instance):
            return True
        await asyncio.sleep(0.3)
    return False


async def _spawn(instance) -> asyncio.subprocess.Process:
    binary = instance_path(instance.binary_path)
    if not binary.is_file():
        raise CpaError(f"CLIProxyAPI 可执行文件不存在：{binary}")

    workdir = instance_install_dir(instance)
    if not workdir.is_dir():
        raise CpaError(f"实例安装目录不存在：{workdir}")

    log_path = instance_path(instance.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab")
    try:
        return await asyncio.create_subprocess_exec(
            str(binary),
            "--config",
            str(instance_path(instance.config_path)),
            cwd=str(workdir),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        # 缺动态加载器/依赖库同样抛 OSError，统一转成可预期的 CpaError。
        raise CpaError(f"启动 CLIProxyAPI 子进程失败：{exc}") from exc
    finally:
        # 子进程已复制该描述符，父进程可以安全关闭自己的副本。
        log_file.close()


def _track_process(instance_id: str, process: asyncio.subprocess.Process) -> None:
    _processes[instance_id] = process

    async def reaper() -> None:
        try:
            await process.wait()
        except asyncio.CancelledError:
            return
        finally:
            _reapers.pop(instance_id, None)
            _processes.pop(instance_id, None)

    _reapers[instance_id] = asyncio.create_task(reaper())


async def start_instance(instance) -> None:
    """启动实例并等待健康检查通过。已存活的实例会被接管而不是重复启动。"""
    if not instance.binary_path:
        raise CpaError("实例尚未安装 CLIProxyAPI 二进制")

    ensure_instance_layout(instance)
    write_config(instance)

    if await is_instance_running(instance):
        logger.info("CLIProxyAPI instance already running", extra={"instance": instance.name})
        return

    process = await _spawn(instance)
    _track_process(instance.id, process)
    instance.pid = process.pid
    write_pid(instance, process.pid)

    if not await wait_until_healthy(instance):
        await stop_instance(instance)
        raise CpaError("CLIProxyAPI 启动后未能通过 /healthz 健康检查，请查看实例日志")

    logger.info("CLIProxyAPI instance started", extra={"instance": instance.name, "pid": process.pid})


async def stop_instance(instance, timeout: float = 10.0) -> None:
    pid = instance.pid or read_pid(instance)
    if not is_process_alive(pid):
        clear_pid(instance)
        return

    assert pid is not None
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            clear_pid(instance)
            return

    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not is_process_alive(pid):
            clear_pid(instance)
            return
        await asyncio.sleep(STOP_POLL_INTERVAL)

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    clear_pid(instance)
    logger.warning("CLIProxyAPI instance force killed", extra={"instance": instance.name, "pid": pid})


async def restart_instance(instance) -> None:
    await stop_instance(instance)
    await start_instance(instance)


async def is_instance_running(instance) -> bool:
    pid = instance.pid or read_pid(instance)
    if not is_process_alive(pid):
        return False
    return await probe_health(instance)


async def runtime_status(instance) -> str:
    """返回 stopped / starting / running / error 之一。"""
    pid = instance.pid or read_pid(instance)
    if not is_process_alive(pid):
        return "stopped"
    if await probe_health(instance):
        return "running"
    return "starting"


def serialize_instance(instance, *, status: str) -> dict[str, Any]:
    """序列化实例供管理接口返回。

    `management_key` 是 CLIProxyAPI 的控制面密钥，管理界面不需要它，
    因此不从接口暴露；需要时可直接读取实例配置文件（config_path）。
    access_key 是调用 CPA 的客户端密钥，与渠道凭据同源，保留用于调试。
    """
    return {
        "id": instance.id,
        "name": instance.name,
        "host": instance.host,
        "port": instance.port,
        "base_url": instance_base_url(instance),
        "version": instance.version,
        "binary_path": instance.binary_path,
        "managed_binary": instance.managed_binary,
        "install_dir": instance.install_dir,
        "config_path": instance.config_path,
        "auth_dir": instance.auth_dir,
        "log_path": instance.log_path,
        "auto_start": instance.auto_start,
        "status": status,
        "pid": instance.pid,
        "access_key": access_key(instance),
        "last_error": instance.last_error or "",
        "last_started_at": instance.last_started_at.isoformat() if instance.last_started_at else "",
        "created_at": instance.created_at.isoformat() if instance.created_at else "",
        "updated_at": instance.updated_at.isoformat() if instance.updated_at else "",
    }


async def get_or_create_instance(session):
    """返回唯一的托管实例，不存在时按默认配置创建。

    托管实例固定为单例：端口自动分配，安装目录位于
    ``install_root()/instances/<id>``，管理员无需（也不能）手工增删改。
    若数据库里残留多条实例记录，只选用一条并告警，不擅自删除其凭据文件。
    """
    from sqlalchemy import select

    from app.models.cpa_instance import CpaInstance

    result = await session.execute(select(CpaInstance).order_by(CpaInstance.created_at))
    instances = result.scalars().all()
    if instances:
        # 遗留的多实例记录中优先选正在运行的那条，避免接管到已停止的实例。
        primary = next((item for item in instances if item.status == "running"), instances[0])
        if len(instances) > 1:
            logger.warning(
                "检测到多条 CLIProxyAPI 实例记录，单实例模式只使用其中一条",
                extra={"instance": primary.name, "ignored": len(instances) - 1},
            )
        return primary

    instance = CpaInstance(
        id=str(uuid.uuid4()),
        name=SINGLETON_INSTANCE_NAME,
        host="127.0.0.1",
        port=0,
        auto_start=True,
        managed_binary=True,
    )
    initialize_instance(instance)
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    logger.info("已创建托管的 CLIProxyAPI 单实例", extra={"instance": instance.name})
    return instance


async def reconcile_instances() -> None:
    """应用启动时对齐托管的单实例：接管已运行进程，按需拉起并同步托管渠道。"""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        instance = await get_or_create_instance(session)

    try:
        status = await runtime_status(instance)
        if status == "running":
            instance.status = "running"
            if not instance.pid:
                instance.pid = read_pid(instance)
            instance.last_error = ""
        elif instance.auto_start:
            if not instance.binary_path:
                instance.status = "error"
                instance.last_error = "未安装 CLIProxyAPI 二进制"
            else:
                await start_instance(instance)
                instance.status = "running"
                instance.last_error = ""
        else:
            instance.status = "stopped"
    except Exception as exc:
        instance.status = "error"
        instance.last_error = str(exc)[:500]
        logger.error(
            "CLIProxyAPI instance reconcile failed",
            extra={"instance": instance.name, "error": str(exc)},
        )

    async with AsyncSessionLocal() as session:
        await session.merge(instance)
        await session.commit()

    try:
        await sync_managed_channels(instance)
    except Exception as exc:  # 渠道同步失败不影响实例本身
        logger.error(
            "CLIProxyAPI managed channel sync failed",
            extra={"instance": instance.name, "error": str(exc)},
        )

    # 实例可用时确保默认插件在位。安装要下载 GitHub Release 并等 CPA 热加载，
    # 必须放后台：否则会阻塞应用启动本身（历史上曾因此卡住 30 秒以上）。
    if instance.status == "running":
        schedule_quota_plugin_setup(instance)


def schedule_quota_plugin_setup(instance) -> None:
    """后台确认/安装配额插件，失败只记录。"""
    if not settings.cpa_quota_plugin_enabled:
        return

    async def _run() -> None:
        try:
            # 延迟导入：cpa_quota 依赖本模块的地址与密钥工具。
            from app.services.cpa_quota import ensure_plugin

            state = await ensure_plugin(instance)
            if not state.get("available"):
                logger.warning(f"配额插件不可用：{state.get('reason') or state}")
        except Exception as exc:  # 插件不可用不影响实例与其渠道
            logger.error(f"安装配额插件时出错：{exc}")

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def shutdown_reapers() -> None:
    for task in list(_reapers.values()):
        task.cancel()
    _reapers.clear()
    for task in list(_background_tasks):
        task.cancel()
    _background_tasks.clear()
    _processes.clear()


# --------------------------------------------------------------------------
# 自动托管渠道
# --------------------------------------------------------------------------

CPA_CHANNEL_PREFIX = "CliProxyAPI-"
MODEL_LIST_TIMEOUT = 15.0


def channel_name_for_provider(provider: str) -> str:
    """托管渠道名：``CliProxyAPI-<账号类型>``，类型使用界面显示标签。"""
    # 延迟导入：cpa_accounts 依赖本模块的密钥与地址工具。
    from app.services.cpa_accounts import provider_label

    return f"{CPA_CHANNEL_PREFIX}{provider_label(provider)}"


async def fetch_available_models(instance) -> list[str]:
    """读取实例通过 /v1/models 暴露的模型列表。"""
    url = f"{instance_base_url(instance)}/v1/models"
    headers = {"Authorization": f"Bearer {access_key(instance)}"}
    try:
        async with httpx.AsyncClient(timeout=MODEL_LIST_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning(f"获取 CLIProxyAPI 模型列表失败：{exc}")
        return []
    if response.status_code >= 400:
        logger.warning(
            f"获取 CLIProxyAPI 模型列表返回 HTTP {response.status_code}",
            extra={"instance": instance.name},
        )
        return []

    try:
        payload = response.json()
    except ValueError:
        return []

    candidates = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(candidates, list):
        candidates = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(candidates, list):
        return []

    models: list[str] = []
    for item in candidates:
        if isinstance(item, str):
            models.append(item)
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
            if isinstance(model_id, str) and model_id:
                models.append(model_id)
    return sorted(dict.fromkeys(models))


async def _models_by_provider(instance, files: list[dict]) -> dict[str, list[str]]:
    """按账号类型归并上游模型：逐个账号读取其可用模型后去重合并。"""
    from app.services import cpa_accounts

    grouped: dict[str, list[str]] = {}
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        try:
            models = await cpa_accounts.list_auth_file_models(instance, name)
        except cpa_accounts.CpaManagementError as exc:
            logger.warning(f"读取账号 {name} 的模型列表失败：{exc}")
            continue
        if models:
            grouped.setdefault(cpa_accounts.account_provider(entry), []).extend(models)

    return {key: sorted(dict.fromkeys(values)) for key, values in grouped.items()}


async def sync_managed_channels(instance, *, refresh_models: bool = True) -> list[str]:
    """按账号类型同步托管渠道，返回这些渠道的 ID。

    每种账号类型对应一个渠道，名称为 ``CliProxyAPI-<账号类型>``，
    ``auto_managed = True``、``health_check_mode = "account_pool"``，
    并用 ``cpa_provider`` 记录类型，使健康判定只统计该类型的账号。
    没有账号的类型不建渠道；账号被清空的类型会移除其渠道；历史遗留的实例级
    渠道（``cpa_provider`` 为空）一并清理。账号池读取不到时只刷新既有渠道的
    地址与密钥，不增删类型，避免实例停机被误判成「没有账号」。
    """
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.channel import Channel
    from app.services import cpa_accounts

    if not instance.id:
        return []

    files: list[dict] = []
    pool_known = False
    if refresh_models and await probe_health(instance):
        try:
            files = await cpa_accounts.list_auth_files(instance)
        except cpa_accounts.CpaManagementError as exc:
            logger.warning(f"读取 CLIProxyAPI 账号池失败，保留现有托管渠道：{exc}")
        else:
            pool_known = True

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Channel).where(Channel.cpa_instance_id == instance.id)
        )
        existing = {channel.cpa_provider: channel for channel in result.scalars().all()}

        if not pool_known:
            managed_ids: list[str] = []
            for provider, channel in existing.items():
                if provider is None:
                    # 历史遗留的实例级渠道：无论账号池是否可知都不再需要。
                    await session.delete(channel)
                    continue
                channel.base_url = instance_base_url(instance)
                channel.encrypted_api_key = instance.encrypted_access_key
                channel.auto_managed = True
                managed_ids.append(channel.id)
            await session.commit()
            return managed_ids

        summaries = cpa_accounts.summarize_by_provider(files)
        models_by_provider = await _models_by_provider(instance, files)

        managed_ids = []
        for provider in summaries:
            channel = existing.pop(provider, None)
            is_new = channel is None
            if is_new:
                channel = Channel(
                    id=str(uuid.uuid4()),
                    name=channel_name_for_provider(provider),
                    provider="cliproxyapi",
                    api_type="openai",
                    base_url=instance_base_url(instance),
                    encrypted_api_key=instance.encrypted_access_key or "",
                    upstream_models=[],
                )
                session.add(channel)

            channel.name = channel_name_for_provider(provider)
            channel.provider = "cliproxyapi"
            channel.base_url = instance_base_url(instance)
            channel.encrypted_api_key = instance.encrypted_access_key
            channel.health_check_mode = "account_pool"
            channel.health_check_model = ""
            channel.auto_managed = True
            channel.cpa_instance_id = instance.id
            channel.cpa_provider = provider
            models = models_by_provider.get(provider)
            if models:
                channel.upstream_models = models
            elif is_new:
                channel.upstream_models = []

            managed_ids.append(channel.id)

        # 账号池已知：已经没有账号的类型（含历史遗留的实例级渠道）一律移除。
        for channel in existing.values():
            await session.delete(channel)

        await session.commit()
        return managed_ids


async def remove_managed_channels(instance_id: str) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.channel import Channel

    async with AsyncSessionLocal() as session:
        await session.execute(delete(Channel).where(Channel.cpa_instance_id == instance_id))
        await session.commit()
