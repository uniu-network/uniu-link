import asyncio
import os
import shutil
import socket
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_frontend_process: asyncio.subprocess.Process | None = None
_frontend_dev_url: str | None = None

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


def is_development() -> bool:
    return settings.app_env.lower() in {"development", "dev", "local"}


def frontend_dev_url() -> str:
    if _frontend_dev_url is None:
        raise RuntimeError("Frontend dev server is not started")
    return _frontend_dev_url


def _get_loopback_host() -> str:
    return socket.gethostbyname("localhost")


def _get_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


async def is_frontend_dev_server_ready() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(frontend_dev_url())
        return response.status_code < 500
    except Exception:
        return False


async def start_frontend_dev_server() -> None:
    global _frontend_process, _frontend_dev_url
    if not is_development() or _frontend_process is not None:
        return

    host = _get_loopback_host()
    port = _get_free_port(host)
    _frontend_dev_url = f"http://{host}:{port}"
    command = ["npm", "run", "dev", "--", "--host", host, "--port", str(port), "--strictPort"]
    if shutil.which("yarn"):
        command = ["yarn", "dev", "--host", host, "--port", str(port), "--strictPort"]

    env = os.environ.copy()
    env["BROWSER"] = "none"
    _frontend_process = await asyncio.create_subprocess_exec(
        *command,
        cwd=FRONTEND_DIR,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    logger.info("Started frontend dev server", extra={"command": " ".join(command), "url": frontend_dev_url()})
    asyncio.create_task(_stream_frontend_logs(_frontend_process))
    for _ in range(30):
        if await is_frontend_dev_server_ready():
            return
        await asyncio.sleep(0.5)
    logger.warning("Frontend dev server did not become ready in time", extra={"url": frontend_dev_url()})


async def _stream_frontend_logs(process: asyncio.subprocess.Process) -> None:
    if process.stdout is None:
        return
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        logger.info("frontend: " + line.decode(errors="replace").rstrip())


async def stop_frontend_dev_server() -> None:
    global _frontend_process, _frontend_dev_url
    if _frontend_process is None:
        _frontend_dev_url = None
        return

    _frontend_process.terminate()
    try:
        await asyncio.wait_for(_frontend_process.wait(), timeout=5)
    except asyncio.TimeoutError:
        _frontend_process.kill()
        await _frontend_process.wait()
    logger.info("Stopped frontend dev server")
    _frontend_process = None
    _frontend_dev_url = None
