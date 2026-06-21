import hashlib
from typing import Any

from app.plugins.plugin_engine import PluginHook
from app.core.logging import get_logger
from app.core.database import AsyncSessionLocal
from app.models.request_log import RequestLog

logger = get_logger(__name__)


def _limit(value: Any, max_length: int) -> str:
    text = "" if value is None else str(value)
    return text[:max_length]


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class LoggingPlugin(PluginHook):

    name = "logging"
    version = "1.0.0"

    async def post_send(self, context: dict):
        try:
            api_key_hash = _limit(context.get("api_key_hash", ""), 128)
            key_hash = hashlib.sha256(api_key_hash.encode()).hexdigest()[:16] if api_key_hash else ""

            log_entry = RequestLog(
                trace_id=_limit(context.get("trace_id", ""), 64),
                api_key_hash=key_hash,
                from_apikey=_limit(context.get("from_apikey", ""), 36),
                from_apikey_name=_limit(context.get("from_apikey_name", ""), 128),
                api_type=_limit(context.get("api_type", ""), 16),
                model=_limit(context.get("model", ""), 128),
                selected_channel_id=_limit(context.get("channel_id", ""), 36),
                selected_channel_name=_limit(context.get("channel_name", ""), 128),
                upstream_url=_limit(context.get("upstream_url", ""), 1024),
                latency_ms=_to_float(context.get("latency_ms", 0)),
                status_code=_to_int(context.get("status_code", 0)),
                error_message=_limit(context.get("error_message", ""), 1000),
                thinking_effort=_limit(context.get("thinking_effort", "none"), 16) or "none",
                prompt_tokens=_to_int(context.get("prompt_tokens", 0)),
                completion_tokens=_to_int(context.get("completion_tokens", 0)),
                total_tokens=_to_int(context.get("total_tokens", 0)),
                cache_tokens=_to_int(context.get("cache_tokens", 0)),
                request_body=_limit(context.get("request_body", ""), 100000),
                response_body=_limit(context.get("response_body", ""), 100000),
                input_content=_limit(context.get("input_content", ""), 50000),
                output_content=_limit(context.get("output_content", ""), 50000),
            )

            async with AsyncSessionLocal() as session:
                session.add(log_entry)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to save request log: {e}")
