import json
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


_ANTHROPIC_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    402: "billing_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
    500: "api_error",
    503: "overloaded_error",
    504: "timeout_error",
    529: "overloaded_error",
}

_OPENAI_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "invalid_request_error",
    429: "rate_limit_error",
    500: "api_error",
    503: "api_error",
    504: "api_error",
    529: "api_error",
}


def _extract_error_payload(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict):
            return error
        return detail
    return {"message": str(detail)}


def extract_error_message(detail: Any) -> str:
    payload = _extract_error_payload(detail)
    message = payload.get("message")
    if isinstance(message, str):
        return message
    if message is not None:
        return str(message)
    try:
        return json.dumps(detail, ensure_ascii=False)
    except Exception:
        return str(detail)


def api_error_type(status_code: int, api_type: str, detail: Any = None) -> str:
    payload = _extract_error_payload(detail)
    error_type = payload.get("type")
    if isinstance(error_type, str) and error_type:
        return error_type
    if api_type == "claude":
        return _ANTHROPIC_ERROR_TYPES.get(status_code, "api_error")
    return _OPENAI_ERROR_TYPES.get(status_code, "api_error")


def api_error_body(
    status_code: int,
    message: str,
    api_type: str,
    *,
    error_type: str | None = None,
    code: str | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    resolved_type = error_type or api_error_type(status_code, api_type)
    if api_type == "claude":
        body: dict[str, Any] = {
            "type": "error",
            "error": {
                "type": resolved_type,
                "message": message,
            },
        }
        if request_id:
            body["request_id"] = request_id
        return body

    return {
        "error": {
            "message": message,
            "type": resolved_type,
            "param": None,
            "code": code,
        }
    }


def api_error_response(
    status_code: int,
    message: str,
    api_type: str,
    *,
    error_type: str | None = None,
    code: str | None = None,
    request_id: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=api_error_body(
            status_code,
            message,
            api_type,
            error_type=error_type,
            code=code,
            request_id=request_id,
        ),
    )


def api_type_from_path(path: str) -> str:
    if path.startswith("/v1/messages"):
        return "claude"
    return "openai"
