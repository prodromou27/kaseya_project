"""Structured JSON logging with request IDs and secret redaction."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from .redaction import redact, redact_text
from .request_context import get_request_id

_STANDARD_ATTRS = set(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None).__dict__.keys()) | {
    "message",
    "asctime",
    "request_id",
}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class RedactingFilter(logging.Filter):
    """Redacts the rendered message, args, extras and exception text before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            message = str(record.msg)
        record.msg = redact_text(message)
        record.args = None
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD_ATTRS:
                record.__dict__[key] = redact({key: value})[key]
        if record.exc_info:
            record.exc_text = redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, default=str)
