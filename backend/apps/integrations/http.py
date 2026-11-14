"""Read-only, egress-checked HTTP client for vendor connectors.

Guarantees (AGENTS.md / SECURITY.md §3 / API_INTEGRATIONS.md §1):

* **GET only.** There is no method to send anything else.
* **Default-deny endpoint allowlist** per adapter (regex on path).
* **Egress policy** re-validated on every request: base URL allowlist + DNS resolution check that rejects
  loopback/link-local/metadata and unapproved private addresses. Redirects are never followed.
* **TLS verification always on** (``verify=True`` is hard-coded; there is no parameter to disable it).
* **Rate budget** per client (``max_rps``), honours ``Retry-After`` on 429 (bounded), bounded exponential
  backoff on 5xx/timeouts, and **no retry on 401/403** (VSA counts failed requests against a per-IP limit).
* Error bodies are never read into exceptions or logs; only the status code is kept.

Residual risk: DNS can change between the resolution check and the connection (rebinding). Production must
also enforce an egress firewall allowlist (P5-02).
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests
from django.core.exceptions import ValidationError

from .urlpolicy import _ALWAYS_BLOCKED_NETWORKS, _approved_private_networks, validate_connector_base_url

logger = logging.getLogger("portal.connectors")

MAX_RETRY_AFTER_SECONDS = 300
DEFAULT_TIMEOUT = (5, 30)


class ConnectorError(Exception):
    code = "connector_error"
    retryable = False

    def __init__(self, message: str = "", *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message or self.code)
        self.status = status
        self.retry_after = retry_after


class EgressBlocked(ConnectorError):
    code = "egress_blocked"


class EndpointNotAllowed(ConnectorError):
    code = "endpoint_not_allowed"


class VendorAuthError(ConnectorError):
    code = "auth_failed"


class VendorRateLimited(ConnectorError):
    code = "rate_limited"
    retryable = True


class VendorUnavailable(ConnectorError):
    code = "vendor_unavailable"
    retryable = True


class VendorBadResponse(ConnectorError):
    code = "bad_response"


class VendorClientError(ConnectorError):
    code = "vendor_client_error"


@dataclass
class HttpResult:
    status: int
    json: Any
    headers: Mapping[str, str]


class Transport(Protocol):
    def get(self, url: str, *, params: Mapping[str, str], headers: Mapping[str, str], auth: Any) -> Any: ...


class RequestsTransport:
    """Real network transport. TLS verification and no-redirect are not configurable."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.trust_env = False  # ignore ambient proxy/netrc credentials

    def get(self, url: str, *, params: Mapping[str, str], headers: Mapping[str, str], auth: Any) -> Any:
        return self.session.get(
            url, params=params, headers=headers, auth=auth, timeout=DEFAULT_TIMEOUT, allow_redirects=False, verify=True
        )


Resolver = Callable[[str], Sequence[str]]


def default_resolver(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})


def check_resolved_addresses(host: str, provider: str, resolver: Resolver) -> None:
    try:
        addresses = resolver(host)
    except OSError as exc:
        raise VendorUnavailable("DNS resolution failed.") from exc
    if not addresses:
        raise VendorUnavailable("DNS resolution returned no addresses.")
    approved = _approved_private_networks() if provider == "vsa_x" else []
    for raw in addresses:
        ip = ipaddress.ip_address(raw.split("%")[0])
        if any(ip in net for net in _ALWAYS_BLOCKED_NETWORKS):
            raise EgressBlocked("Destination resolves to a blocked address.")
        if (ip.is_private or ip.is_reserved or ip.is_multicast) and not any(ip in net for net in approved):
            raise EgressBlocked("Destination resolves to an unapproved private address.")


class ReadOnlyHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        provider: str,
        allowed_paths: Sequence[re.Pattern[str]],
        auth: Any,
        max_rps: float,
        transport: Transport | None = None,
        resolver: Resolver | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_retries: int = 4,
        is_fixture: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.allowed_paths = list(allowed_paths)
        self.auth = auth
        self.min_interval = 1.0 / max(max_rps, 0.01)
        self.transport = transport or RequestsTransport()
        self.resolver = resolver or default_resolver
        self.sleep = sleeper
        self.clock = clock
        self.max_retries = max_retries
        self.is_fixture = is_fixture
        self._last_request_at: float | None = None
        self.request_count = 0
        if is_fixture and isinstance(self.transport, RequestsTransport):
            raise EgressBlocked("Fixture instances can never use the network transport.")

    # -- policy -----------------------------------------------------------------------------------
    def _check_egress(self) -> None:
        host = urlsplit(self.base_url).hostname or ""
        if self.is_fixture:
            if not host.endswith(".invalid"):
                raise EgressBlocked("Fixture instance with a non-.invalid host.")
            return
        try:
            validate_connector_base_url(self.base_url, self.provider)
        except ValidationError as exc:
            raise EgressBlocked("Base URL is no longer on the egress allowlist.") from exc
        try:
            ipaddress.ip_address(host)
            return  # IP literal already validated against approved CIDRs by the URL policy
        except ValueError:
            check_resolved_addresses(host, self.provider, self.resolver)

    def _check_path(self, path: str) -> None:
        if not path.startswith("/") or ".." in path or "//" in path:
            raise EndpointNotAllowed("Malformed path.")
        if not any(p.fullmatch(path) for p in self.allowed_paths):
            raise EndpointNotAllowed(f"Path not on the {self.provider} read-only allowlist.")

    def _throttle(self) -> None:
        now = self.clock()
        if self._last_request_at is not None:
            wait = self.min_interval - (now - self._last_request_at)
            if wait > 0:
                self.sleep(wait)
        self._last_request_at = self.clock()

    # -- request ----------------------------------------------------------------------------------
    def get_json(
        self, path: str, params: Mapping[str, str] | None = None, *, max_retries: int | None = None
    ) -> HttpResult:
        """``max_retries`` overrides the client default for timeouts and 5xx (not for 429)."""
        retries = self.max_retries if max_retries is None else max_retries
        self._check_path(path)
        self._check_egress()
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            self.request_count += 1
            try:
                resp = self.transport.get(
                    url, params=dict(params or {}), headers={"Accept": "application/json"}, auth=self.auth
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt > retries:
                    raise VendorUnavailable("Timed out or connection failed.") from exc
                self.sleep(min(2**attempt, 60))
                continue
            status = int(resp.status_code)
            if status in (401, 403):
                raise VendorAuthError("Vendor rejected the credentials.", status=status)
            if status == 429:
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if attempt > self.max_retries or retry_after > MAX_RETRY_AFTER_SECONDS:
                    raise VendorRateLimited("Rate limit budget exhausted.", status=429, retry_after=retry_after)
                logger.warning("vendor_rate_limited", extra={"provider": self.provider, "retry_after": retry_after})
                self.sleep(retry_after)
                continue
            if 300 <= status < 400:
                raise EgressBlocked("Redirects are not followed.", status=status)
            if status >= 500:
                if attempt > retries:
                    raise VendorUnavailable("Vendor server error.", status=status)
                self.sleep(min(2**attempt, 60))
                continue
            if status >= 400:
                raise VendorClientError("Vendor rejected the request.", status=status)
            try:
                body = resp.json()
            except ValueError as exc:
                raise VendorBadResponse("Response was not valid JSON.", status=status) from exc
            return HttpResult(status=status, json=body, headers=dict(resp.headers))


def _parse_retry_after(value: str | None) -> float:
    try:
        seconds = float(value) if value is not None else 60.0
    except ValueError:
        seconds = 60.0
    return max(1.0, seconds)
