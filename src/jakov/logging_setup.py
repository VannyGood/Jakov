"""structlog + stdlib logging with file rotation and secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

# Telegram bot tokens look like 123456789:AA... (35 chars after the colon). No leading \b:
# in API URLs the token directly follows "bot" (".../bot123:AA.../getMe").
_TOKEN_RE = re.compile(r"(?<![0-9])\d{6,12}:[A-Za-z0-9_-]{30,}")
REDACTED = "***"


class SecretRedactor:
    """Removes known secret values and anything shaped like a bot token."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = sorted({s for s in secrets if len(s) >= 6}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return _TOKEN_RE.sub(REDACTED, text)

    def __call__(self, _logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        return {k: self.redact(v) if isinstance(v, str) else v for k, v in event_dict.items()}


class _RedactingFilter(logging.Filter):
    def __init__(self, redactor: SecretRedactor) -> None:
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        # structlog events arrive as dicts and are redacted by the SecretRedactor processor;
        # plain stdlib records (aiogram, aiohttp, ...) are redacted here.
        if isinstance(record.msg, str):
            record.msg = self._redactor.redact(record.getMessage())
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self._redactor.redact(record.exc_text)
        return True


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    secrets: Iterable[str] = (),
    json_logs: bool = False,
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    redactor = SecretRedactor(secrets)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redactor,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    def formatter(renderer: Any) -> structlog.stdlib.ProcessorFormatter:
        return structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter(
        structlog.processors.JSONRenderer() if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    ))
    file_handler = RotatingFileHandler(
        log_dir / "jakov.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter(structlog.processors.JSONRenderer()))

    redacting = _RedactingFilter(redactor)
    root = logging.getLogger()
    root.handlers.clear()
    for handler in (console, file_handler):
        handler.addFilter(redacting)
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)
