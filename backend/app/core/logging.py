import logging
import sys
from pathlib import Path
from pythonjsonlogger import jsonlogger

from app.core.config import settings


JSON_LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s %(trace_id)s"
TEXT_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | trace=%(trace_id)s | %(message)s"
RESET = "\033[0m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
LEVEL_COLORS = {
    logging.DEBUG: DIM,
    logging.INFO: GREEN,
    logging.WARNING: YELLOW,
    logging.ERROR: RED,
    logging.CRITICAL: MAGENTA,
}
TEXT_EXTRA_FIELDS = (
    "http_method",
    "upstream_url",
    "status_code",
    "channel",
    "request_body",
    "response_body",
)
_configured = False


class LogDefaultsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        extras = []
        for field in TEXT_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, ""):
                extras.append(f"{field}={value}")
        if extras:
            return text + " | " + " | ".join(extras)
        return text


class ColoredTextFormatter(TextFormatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        level_color = LEVEL_COLORS.get(record.levelno, RESET)
        return text.replace(record.levelname, f"{level_color}{record.levelname}{RESET}", 1)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return f"{DIM}{super().formatTime(record, datefmt)}{RESET}"

    def formatMessage(self, record: logging.LogRecord) -> str:
        message = super().formatMessage(record)
        return message.replace(record.name, f"{CYAN}{record.name}{RESET}", 1)


def _make_json_formatter() -> logging.Formatter:
    return jsonlogger.JsonFormatter(JSON_LOG_FORMAT, timestamp=True)


def _make_text_formatter() -> logging.Formatter:
    if sys.stdout.isatty():
        return ColoredTextFormatter(TEXT_LOG_FORMAT)
    return TextFormatter(TEXT_LOG_FORMAT)


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    handlers: list[logging.Handler] = []
    defaults_filter = LogDefaultsFilter()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.addFilter(defaults_filter)
    console_handler.setFormatter(_make_json_formatter() if settings.raw_json_log else _make_text_formatter())
    handlers.append(console_handler)

    if settings.log_file:
        log_path = Path(settings.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.addFilter(defaults_filter)
        file_handler.setFormatter(_make_json_formatter())
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    root_logger.handlers = handlers
    root_logger.setLevel(settings.log_level.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(settings.log_level.upper())

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    logger = logging.getLogger(name)
    logger.setLevel(settings.log_level.upper())
    return logger


configure_logging()
