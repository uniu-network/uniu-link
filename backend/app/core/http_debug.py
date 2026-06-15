import json
import logging
from typing import Any


MAX_DEBUG_BODY_LENGTH = 20000


def _serialize_body(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, bytes):
        text = body.decode(errors="replace")
    elif isinstance(body, str):
        text = body
    else:
        try:
            text = json.dumps(body, ensure_ascii=False, default=str)
        except Exception:
            text = str(body)
    if len(text) > MAX_DEBUG_BODY_LENGTH:
        return text[:MAX_DEBUG_BODY_LENGTH] + f"...<truncated {len(text) - MAX_DEBUG_BODY_LENGTH} chars>"
    return text


def log_upstream_request(
    logger: logging.Logger,
    method: str,
    url: str,
    body: Any = None,
    trace_id: str = "-",
    channel: str = "",
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "Upstream request body",
        extra={
            "trace_id": trace_id,
            "http_method": method,
            "upstream_url": url,
            "channel": channel,
            "request_body": _serialize_body(body),
        },
    )


def log_upstream_response(
    logger: logging.Logger,
    method: str,
    url: str,
    status_code: int,
    body: Any = None,
    trace_id: str = "-",
    channel: str = "",
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug(
        "Upstream response body",
        extra={
            "trace_id": trace_id,
            "http_method": method,
            "upstream_url": url,
            "status_code": status_code,
            "channel": channel,
            "response_body": _serialize_body(body),
        },
    )
