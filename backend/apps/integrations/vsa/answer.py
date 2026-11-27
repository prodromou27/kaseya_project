"""Who answered a VSA X write: a safe fingerprint of a 2xx answer (2026-11-27).

Live tenant: PUT writes (group move, custom field update) answer OK without being applied, POST (custom field assign)
works - typical of a WAF or proxy answering for the API. To tell them apart without storing the answer body (which may
contain data), only this is kept:

* the ``<title>`` of an HTML answer (block pages carry "Request Rejected", "Access Denied", a support ID, ...),
* an allowlist of headers that name a proxy, CDN or WAF (values cut to 120 characters),
* the *names* of cookies the answer sets (F5 ``TS...``, Imperva ``incap_ses...``) - never their values.
"""

from __future__ import annotations

import html
import re
from typing import Any

HEADERS = (
    "Server",
    "Via",
    "X-Powered-By",
    "X-Cache",
    "X-CDN",
    "CF-Ray",
    "X-Iinfo",
    "X-Sucuri-ID",
    "X-Azure-Ref",
    "X-Amz-Cf-Id",
    "X-Akamai-Transformed",
    "X-Proxy-Cache",
    "Location",
)
_TITLE = re.compile(rb"<title[^>]*>(.{0,400}?)</title>", re.IGNORECASE | re.DOTALL)
_COOKIE_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]{1,64})=")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _clean(value: str, limit: int) -> str:
    return _CONTROL.sub(" ", value).strip()[:limit]


def fingerprint(resp: Any) -> dict[str, Any]:
    headers = getattr(resp, "headers", None) or {}
    found = {name: _clean(str(headers.get(name)), 120) for name in HEADERS if headers.get(name)}
    raw_cookies = []
    raw = getattr(headers, "raw", None)
    if raw is not None and hasattr(raw, "headers") and hasattr(raw.headers, "get_all"):  # pragma: no cover - urllib3
        raw_cookies = raw.headers.get_all("Set-Cookie") or []
    elif headers.get("Set-Cookie"):
        raw_cookies = str(headers.get("Set-Cookie")).split(",")
    cookies = sorted({m.group(1) for c in raw_cookies if (m := _COOKIE_NAME.match(str(c)))})[:10]
    title = ""
    content = getattr(resp, "content", b"") or b""
    if isinstance(content, bytes) and (match := _TITLE.search(content[:65536])):
        title = _clean(html.unescape(match.group(1).decode("utf-8", "replace")), 150)
    return {"title": title, "headers": found, "cookie_names": cookies}


def describe(fp: dict[str, Any] | None) -> str:
    """One line for the portal: 'page title "Request Rejected"; Server: BigIP; cookies TS01ab'."""
    if not fp:
        return ""
    parts = []
    if fp.get("title"):
        parts.append(f'page title "{fp["title"]}"')
    parts += [f"{k}: {v}" for k, v in (fp.get("headers") or {}).items()]
    if fp.get("cookie_names"):
        parts.append("sets cookies " + ", ".join(fp["cookie_names"]))
    return "; ".join(parts)
