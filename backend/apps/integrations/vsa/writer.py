"""VSA5-EXEC: the ONLY vendor write in the portal - ``PUT /api/v3/devices/{id}/move`` for an approved group move.

Deliberately separate from the read-only adapter and client (which stay GET-only):

* **Off by default, two switches.** ``settings.VSA_GROUP_MOVE_EXECUTION_ENABLED`` (server environment; cannot be set
  from the portal) AND ``IntegrationInstance.group_move_execution_enabled`` (super admin, audited).
* **Credential.** The integration's API token, or an optional separate write token (entered in the portal,
  Fernet-encrypted and bound to the integration and the purpose "write", or ``env:VSA_WRITE_*``) when one is set.
* **One fixed route.** Exactly ``/api/v3/devices/{identifier}/move`` with body ``{"GroupId": <int>}``.
* **No retries, ever.** A timeout, connection error or 5xx is reported as *outcome unknown*; the caller verifies by
  reading the device back instead of sending the PUT again.
* Same egress policy as the read client (base URL allowlist, DNS check, TLS always verified, redirects refused).
* Error bodies are never read; only the status code is kept. The credential is never logged.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests
from django.conf import settings

from apps.integrations.http import DEFAULT_TIMEOUT, ConnectorError, check_egress, default_resolver
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import (
    CredentialUnavailable,
    can_write,
    resolve_write_auth,
)

MOVE_PATH = re.compile(r"/api/v3/devices/[A-Za-z0-9-]{1,64}/move")
_DEVICE_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


class MoveNotAvailable(Exception):
    """Execution is switched off or not configured. Safe message."""


class MoveRejected(Exception):
    """VSA X answered with a 4xx: the move was not made."""

    def __init__(self, status: int):
        super().__init__(f"VSA X rejected the move (HTTP {status}).")
        self.status = status


class MoveNotSent(Exception):
    """The portal could not reach VSA X before sending (DNS, egress policy): nothing was sent. Safe message."""


class MoveOutcomeUnknown(Exception):
    """No definite answer (timeout, connection error, 5xx, unreadable body). Verify by reading back; never resend."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


class WriteTransport(Protocol):
    def put(self, url: str, *, json: Mapping[str, Any], headers: Mapping[str, str], auth: Any) -> Any: ...


class RequestsWriteTransport:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.trust_env = False

    def put(self, url: str, *, json: Mapping[str, Any], headers: Mapping[str, str], auth: Any) -> Any:
        return self.session.put(
            url,
            json=dict(json),
            headers=headers,
            auth=auth,
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=False,
            verify=True,
        )


def availability(instance: IntegrationInstance) -> tuple[bool, str]:
    """(available, reason shown to users when not). Does not resolve the secret value."""
    if not getattr(settings, "VSA_GROUP_MOVE_EXECUTION_ENABLED", False):
        return False, (
            "Executing moves in VSA X is switched off on this server (VSA_GROUP_MOVE_EXECUTION_ENABLED=false in "
            ".env.prod; set it to true and redeploy)."
        )
    if instance.provider != IntegrationInstance.Provider.VSA_X or not instance.enabled:
        return False, "The VSA X integration is not enabled."
    if not instance.group_move_execution_enabled:
        return False, "Executing moves is not enabled for this VSA X integration."
    if not instance.is_fixture and not can_write(instance):
        return False, "No VSA X API token is configured for this integration."
    return True, ""


class VsaMoveWriter:
    def __init__(self, instance: IntegrationInstance, transport: WriteTransport | None = None, resolver: Any = None):
        ok, reason = availability(instance)
        if not ok:
            raise MoveNotAvailable(reason)
        self.instance = instance
        self.resolver = resolver or default_resolver
        if instance.is_fixture:
            from .fixtures import FixtureWriteTransport

            self.transport: WriteTransport = transport or FixtureWriteTransport(instance)
            self.auth = None
        else:
            if transport is None or isinstance(transport, RequestsWriteTransport):
                transport = RequestsWriteTransport()
            self.transport = transport
            try:
                write = resolve_write_auth(instance)
            except CredentialUnavailable as exc:
                raise MoveNotAvailable("The VSA X API token could not be read.") from exc
            self.auth = (write.username, write.password)

    def move(self, device_id: str, group_id: str) -> dict[str, Any]:
        """Returns ``{"device", "group_id", "group_name"}`` from the 2xx answer. Raises MoveRejected/OutcomeUnknown."""
        if not _DEVICE_ID.fullmatch(device_id or "") or not str(group_id).isdigit():
            raise ValueError("Unsafe device or group identifier.")
        path = f"/api/v3/devices/{device_id}/move"
        if not MOVE_PATH.fullmatch(path):
            raise ValueError("Unsafe path.")
        try:
            check_egress(self.instance.base_url, "vsa_x", is_fixture=self.instance.is_fixture, resolver=self.resolver)
        except ConnectorError as exc:  # before any request: definitely not sent
            host = urlsplit(self.instance.base_url).hostname or "the VSA X host"
            raise MoveNotSent(
                f"Nothing was sent: the portal server could not reach {host} ({exc}). Check DNS and the firewall on "
                "the portal server; the move stays approved and can be sent again."
            ) from exc
        url = f"{self.instance.base_url.rstrip('/')}{path}"
        started = time.monotonic()
        try:
            resp = self.transport.put(
                url,
                json={"GroupId": int(group_id)},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                auth=self.auth,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise MoveOutcomeUnknown("timeout_or_connection") from exc
        status = int(resp.status_code)
        if 200 <= status < 300:
            try:
                data = (resp.json() or {}).get("Data") or {}
            except ValueError as exc:
                raise MoveOutcomeUnknown("unreadable_response", status) from exc
            return {
                "device": str(data.get("DeviceIdentifier") or "")[:64],
                "group_id": str(data.get("GroupId") or "")[:20],
                "group_name": str(data.get("GroupName") or "")[:255],
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        if 300 <= status < 400 or status >= 500:
            raise MoveOutcomeUnknown(f"http_{status}", status)
        raise MoveRejected(status)
