import hashlib
import hmac
import time
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.config import settings
from app.services.redis_client import get_redis


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


NONCE_KEY = "admin_hmac_nonce:{}"
UNAUTHORIZED_RESPONSE = JSONResponse(
    status_code=401,
    content={"error": {"message": "Unauthorized", "type": "auth_error", "code": "401"}},
)


def _compute_signature(method: str, path: str, timestamp: str, nonce: str, body_hash: str) -> str:
    string_to_sign = f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"
    return hmac.new(
        settings.admin_api_key.encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()


async def _verify_hmac(request: Request) -> bool:
    timestamp = request.headers.get("X-Admin-Timestamp", "")
    nonce = request.headers.get("X-Admin-Nonce", "")
    signature = request.headers.get("X-Admin-Signature", "")

    if not timestamp or not nonce or not signature:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > settings.admin_hmac_ttl_seconds:
        return False

    redis = await get_redis()
    nonce_key = NONCE_KEY.format(nonce)
    if await redis.exists(nonce_key):
        return False

    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest() if body else hashlib.sha256(b"").hexdigest()

    expected = _compute_signature(
        request.method, request.url.path, timestamp, nonce, body_hash,
    )
    if not hmac.compare_digest(expected, signature):
        return False

    await redis.set(nonce_key, "1", ex=settings.admin_hmac_ttl_seconds)
    return True


class AdminAuthMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/admin"):
            if not await _verify_hmac(request):
                return UNAUTHORIZED_RESPONSE

        response = await call_next(request)
        return response


def extract_client_api_key(request: Request) -> tuple[str, str]:
    auth_header = request.headers.get("Authorization", "")
    api_key = ""

    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
    elif "x-api-key" in request.headers:
        api_key = request.headers["x-api-key"]
    elif "anthropic-version" in request.headers and auth_header.startswith("x-api-key "):
        api_key = auth_header.split(" ", 1)[1] if " " in auth_header else ""
    elif request.headers.get("x-api-key"):
        api_key = request.headers["x-api-key"]

    api_key_hash = hash_api_key(api_key) if api_key else ""
    return api_key, api_key_hash
