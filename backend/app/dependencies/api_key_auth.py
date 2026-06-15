from fastapi import Request, HTTPException
from app.middleware.auth import extract_client_api_key
from app.services.api_key_service import verify_api_key, check_model_access, check_key_rate_limit

async def require_api_key(request: Request) -> dict:
    raw_key, _ = extract_client_api_key(request)

    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "API key is required. Provide it via Authorization: Bearer <key> or x-api-key header.",
                    "type": "authentication_error",
                    "code": "401",
                }
            },
        )

    key_info = await verify_api_key(raw_key)
    if not key_info:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid, expired, or disabled API key.",
                    "type": "authentication_error",
                    "code": "401",
                }
            },
        )

    if key_info.get("max_tokens") and key_info["max_tokens"] > 0:
        if key_info["used_tokens"] >= key_info["max_tokens"]:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "message": "Token quota exceeded for this API key.",
                        "type": "quota_exceeded",
                        "code": "429",
                    }
                },
            )

    allowed, reason = await check_key_rate_limit(key_info)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "message": reason,
                    "type": "rate_limit_exceeded",
                    "code": "429",
                }
            },
        )

    request.state.api_key_info = key_info
    return key_info
