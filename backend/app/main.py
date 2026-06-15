from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import get_logger
from app.core.database import init_db
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.auth import AdminAuthMiddleware
from app.services.redis_client import get_redis, close_redis
from app.services.health_checker import health_check_loop
from app.services.frontend import start_frontend_dev_server, stop_frontend_dev_server
from app.plugins.plugin_engine import plugin_engine
from app.admin import admin_router
from app.routes.health import router as health_router
from app.routes.openai import router as openai_router
from app.routes.claude import router as claude_router
from app.routes.frontend import router as frontend_router
from app.core.response import (
    api_error_response,
    api_error_type,
    api_type_from_path,
    error_response,
    extract_error_message,
)

logger = get_logger(__name__)


def _is_v1_path(path: str) -> bool:
    return path == "/v1" or path.startswith("/v1/")


def _v1_http_exception_response(request, status_code: int, detail):
    api_type = api_type_from_path(request.url.path)
    return api_error_response(
        status_code=status_code,
        message=extract_error_message(detail),
        api_type=api_type,
        error_type=api_error_type(status_code, api_type, detail),
        code=str(status_code) if api_type != "claude" else None,
        request_id=getattr(request.state, "trace_id", ""),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting UniuLink AI Gateway...")
    await init_db()
    await get_redis()
    await plugin_engine.load_plugins()
    await start_frontend_dev_server()

    import asyncio
    health_task = asyncio.create_task(health_check_loop())

    yield

    logger.info("Shutting down UniuLink AI Gateway...")
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    await stop_frontend_dev_server()
    await close_redis()


app = FastAPI(
    title="UniuLink AI Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AdminAuthMiddleware)
app.add_middleware(RequestIDMiddleware)

app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(health_router)
app.include_router(openai_router)
app.include_router(claude_router)
app.include_router(frontend_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    if _is_v1_path(request.url.path):
        return _v1_http_exception_response(request, exc.status_code, exc.detail)

    return error_response(
        message=exc.detail,
        detail_msg=exc.detail,
        status_code=exc.status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request, exc: StarletteHTTPException):
    if _is_v1_path(request.url.path):
        return _v1_http_exception_response(request, exc.status_code, exc.detail)

    return error_response(
        message=exc.detail,
        detail_msg=exc.detail,
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    logger.exception("Unhandled request error", extra={"path": request.url.path})
    if _is_v1_path(request.url.path):
        api_type = api_type_from_path(request.url.path)
        return api_error_response(
            status_code=500,
            message="Internal server error",
            api_type=api_type,
            error_type=api_error_type(500, api_type),
            code="500" if api_type != "claude" else None,
            request_id=getattr(request.state, "trace_id", ""),
        )

    return error_response(
        message="Internal server error",
        detail_msg=str(exc),
        status_code=500,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, log_config=None)
