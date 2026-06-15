from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.response import success_response, error_response
from app.services.redis_client import get_redis

router = APIRouter()


@router.get("/health")
async def health_check():
    return success_response(
        detail_result={"status": "healthy", "service": settings.app_name},
        message="ok",
    )


@router.get("/ready")
async def readiness_check():
    try:
        redis = await get_redis()
        await redis.ping()
        return success_response(
            detail_result={"status": "ready", "database": "connected", "redis": "connected"},
            message="ok",
        )
    except Exception as e:
        return error_response(
            message=str(e),
            detail_msg=f"Service not ready: {e}",
            status_code=503,
        )
