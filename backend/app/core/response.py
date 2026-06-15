from typing import Any
from fastapi.responses import JSONResponse


def success_response(
    detail_result: Any = None,
    message: str = "success",
    detail_msg: str = "",
) -> dict:
    return {
        "is_success_response": True,
        "message": message,
        "data": {
            "detail_msg": detail_msg,
            "detail_result": detail_result,
        },
    }


def error_response(
    message: str = "error",
    detail_msg: str | None = None,
    status_code: int = 400,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "detail_msg": detail_msg or message,
                "status_code": status_code,
            }
        },
    )
