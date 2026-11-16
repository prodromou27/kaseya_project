"""VSA5-EXEC: the ONLY vendor write in the portal - ``PUT /api/v3/devices/{id}/move`` for an approved group move.

Deliberately separate from the read-only adapter and client (which stay GET-only):

* **Off by default, two switches.** ``settings.VSA_GROUP_MOVE_EXECUTION_ENABLED`` (server environment; cannot be set
  from the portal) AND ``IntegrationInstance.group_move_execution_enabled`` (super admin, audited).
* **Separate write credential.** ``IntegrationInstance.write_credential_ref`` must be ``env:VSA_WRITE_*`` (a Docker
  secret on the host, never stored in the database) and must not be the read token.
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

import requests
from django.conf import settings

from apps.integrations.http import DEFAULT_TIMEOUT, check_egress, default_resolver
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import CredentialUnavailable, resolve_basic, resolve_instance_basic

MOVE_PATH = re.compile(r"/api/v3/devices/[A-Za-z0-9-]{1,64}/move")
_DEVICE_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
WRITE_REF = re.compile(r"env:VSA_WRITE_[A-Z0-9_]{1,50}")


class MoveNotAvailable(Exception):
    """Execution is switched off or not configured. Safe message."""


class MoveRejected(Exception):
    """VSA X answered with a 4xx: the move was not made."""

    def __init__(self, status: int):
        super().__init__(f"VSA X rejected the move (HTTP {status}).")
        self.status = status


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
        return False, "Executing moves in VSA X is switched off on this server."
    if instance.provider != IntegrationInstance.Provider.VSA_X or not instance.enabled:
        return False, "The VSA X integration is not enabled."
    if not instance.group_move_execution_enabled:
        return False, "Executing moves is not enabled for this VSA X integration."
    if not instance.is_fixture and not WRITE_REF.fullmatch(instance.write_credential_ref or ""):
        return False, "No separate VSA X write token is configured for this integration."
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
                write = resolve_basic(instance.write_credential_ref)
            except CredentialUnavailable as exc:
                raise MoveNotAvailable("The VSA X write token could not be read on the server.") from exc
            try:
                read = resolve_instance_basic(instance)
            except CredentialUnavailable:
                read = None
            if read is not None and read.username == write.username:
                raise MoveNotAvailable("The write token must be a separate VSA X API token, not the read token.")
            self.auth = (write.username, write.password)

    def move(self, device_id: str, group_id: str) -> dict[str, Any]:
        """Returns ``{"device", "group_id", "group_name"}`` from the 2xx answer. Raises MoveRejected/OutcomeUnknown."""
        if not _DEVICE_ID.fullmatch(device_id or "") or not str(group_id).isdigit():
            raise ValueError("Unsafe device or group identifier.")
        path = f"/api/v3/devices/{device_id}/move"
        if not MOVE_PATH.fullmatch(path):
            raise ValueError("Unsafe path.")
        check_egress(self.instance.base_url, "vsa_x", is_fixture=self.instance.is_fixture, resolver=self.resolver)
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
