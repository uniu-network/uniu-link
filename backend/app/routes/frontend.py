import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from app.services.frontend import FRONTEND_DIST_DIR, frontend_dev_url, is_development

router = APIRouter()

_RESERVED_PREFIXES = ("api", "v1")
_RESERVED_PATHS = {"health", "ready", "docs", "redoc", "openapi.json"}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def _serve_frontend(path: str, request: Request):
    first_segment = path.split("/", 1)[0]
    if first_segment in _RESERVED_PREFIXES or path in _RESERVED_PATHS:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    if is_development():
        return await proxy_frontend_dev_server(path, request)

    return serve_frontend_static(path)


async def proxy_frontend_dev_server(path: str, request: Request) -> Response:
    target_url = f"{frontend_dev_url()}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    excluded_headers = {"host", "content-length"}
    headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded_headers}
    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        upstream = await client.request(
            request.method,
            target_url,
            content=body,
            headers=headers,
        )

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in {"content-encoding", "transfer-encoding", "connection"}
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


def serve_frontend_static(path: str) -> Response:
    if not FRONTEND_DIST_DIR.exists():
        return JSONResponse(status_code=404, content={"detail": "Frontend build not found"})

    requested = (FRONTEND_DIST_DIR / path).resolve()
    dist_root = FRONTEND_DIST_DIR.resolve()
    if requested.is_file() and dist_root in requested.parents:
        return FileResponse(requested)

    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    return JSONResponse(status_code=404, content={"detail": "Frontend entry not found"})
