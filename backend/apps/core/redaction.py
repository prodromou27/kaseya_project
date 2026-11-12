"""Secret redaction used by logging, audit metadata and error responses.

Defence in depth: callers should never pass secrets in the first place, but anything that does slip
through (vendor error bodies, exception messages, metadata dicts) is scrubbed here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|authorization|auth[_-]?header|cookie|session|"
    r"credential|private[_-]?key|otp|totp|client[_-]?secret|x-api-key|apiintegrationcode|signature)",
    re.IGNORECASE,
)

_VALUE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization headers: "Basic xxx", "Bearer xxx"
    (re.compile(r"(?i)\b(basic|bearer)\s+[A-Za-z0-9._~+/=-]{6,}"), r"\1 " + REDACTED),
    # key=value / key: value pairs where key looks sensitive
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|x-api-key|client_secret|apiintegrationcode)"
            r"(\"?\s*[:=]\s*\"?)([^\s\"'&,;}]+)"
        ),
        r"\1\2" + REDACTED,
    ),
    # Credentials embedded in URLs: scheme://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1" + REDACTED + "@"),
    # JWT-looking blobs
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"), REDACTED),
]


def redact_text(value: str) -> str:
    for pattern, replacement in _VALUE_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys and secret-looking values."""
    if _depth > 8:
        return REDACTED
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if SENSITIVE_KEY_RE.search(key_str):
                out[key_str] = REDACTED
            else:
                out[key_str] = redact(item, _depth=_depth + 1)
        return out
    if isinstance(value, list | tuple | set):
        return [redact(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
