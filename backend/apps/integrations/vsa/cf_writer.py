"""CFA (ADR-031): assign or update a VSA X custom field on ONE device. The second gated vendor write.

Deliberately separate from the read-only adapter/client (which stay GET-only), modelled on the group-move writer:

* **Off by default, three gates.** ``settings.VSA_CUSTOM_FIELD_WRITES_ENABLED`` (server environment), the integration's
  ``custom_field_writes_enabled`` (super admin) and a route confirmed on a test workstation
  (``custom_field_write_route``, set only by the test-workstation validation in the portal or
  ``manage.py vsa_custom_field_validate``). Fixture integrations skip the
  route gate (their writes go to an in-process fake).
* **Credential**: the integration's API token, or the optional separate write token when one is set (shared with
  group moves).
* **Documented routes only**: ``POST /api/v3/[automation/]customfields/{id}/assign`` and
  ``PUT /api/v3/[automation/]customfields/{id}/updateAssigned`` with body
  ``{ContextType: "Device", ContextItemId, UseDefaultValue: false, Value}``. ``unassign`` is never called.
* **No retries.** A timeout, connection error or 5xx is *outcome unknown*; the caller reads the value back.
* Same egress policy as the read client; error bodies are never read; the credential is never logged.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol

import requests
from django.conf import settings

from apps.integrations.http import DEFAULT_TIMEOUT, check_egress, default_resolver
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import (
    CredentialUnavailable,
    can_write,
    resolve_write_auth,
)

ROUTES = ("customfields", "automation/customfields")
WRITE_PATH = re.compile(r"/api/v3/(?:automation/)?customfields/[0-9]{1,18}/(?:assign|updateAssigned)")
_DEVICE_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
MAX_VALUE = 255


class WriteNotAvailable(Exception):
    """Writing is switched off or not configured. Safe message."""


class WriteRejected(Exception):
    """VSA X answered 4xx: nothing was changed."""

    def __init__(self, status: int):
        super().__init__(f"VSA X rejected the change (HTTP {status}).")
        self.status = status


class WriteOutcomeUnknown(Exception):
    """No definite answer. Read the value back; never resend."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


class Transport(Protocol):
    def send(self, method: str, url: str, *, json: Mapping[str, Any], headers: Mapping[str, str], auth: Any) -> Any: ...


class RequestsTransport:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.trust_env = False

    def send(self, method: str, url: str, *, json: Mapping[str, Any], headers: Mapping[str, str], auth: Any) -> Any:
        if method not in ("POST", "PUT"):
            raise ValueError("Only POST and PUT are used.")
        return self.session.request(
            method,
            url,
            json=dict(json),
            headers=headers,
            auth=auth,
            timeout=DEFAULT_TIMEOUT,
            allow_redirects=False,
            verify=True,
        )


def availability(instance: IntegrationInstance) -> tuple[bool, str]:
    """(available, reason shown to users). Does not read the secret."""
    if not getattr(settings, "VSA_CUSTOM_FIELD_WRITES_ENABLED", False):
        return False, "Writing custom fields to VSA X is switched off on this server."
    if instance.provider != IntegrationInstance.Provider.VSA_X or not instance.enabled:
        return False, "The VSA X integration is not enabled."
    if not instance.custom_field_writes_enabled:
        return False, "Assigning custom fields is not enabled for this VSA X integration."
    if instance.is_fixture:
        return True, ""
    if instance.custom_field_write_route not in ROUTES:
        return False, "The custom field route has not been validated on a test workstation yet."
    if not can_write(instance):
        return False, "No VSA X API token is configured for this integration."
    return True, ""


def path_for(route: str, field_id: str, operation: str) -> str:
    if route not in ROUTES or operation not in ("assign", "updateAssigned") or not str(field_id).isdigit():
        raise ValueError("Unsafe route, field or operation.")
    path = f"/api/v3/{route}/{int(field_id)}/{operation}"
    if not WRITE_PATH.fullmatch(path):
        raise ValueError("Unsafe path.")
    return path


class VsaCustomFieldWriter:
    def __init__(
        self,
        instance: IntegrationInstance,
        transport: Transport | None = None,
        resolver: Any = None,
        *,
        route: str | None = None,
        check_gates: bool = True,
    ):
        if check_gates:
            ok, reason = availability(instance)
            if not ok:
                raise WriteNotAvailable(reason)
        self.instance = instance
        self.resolver = resolver or default_resolver
        self.route = route or instance.custom_field_write_route or "customfields"
        if instance.is_fixture:
            from .fixtures import FixtureCustomFieldWriteTransport

            self.transport: Transport = transport or FixtureCustomFieldWriteTransport(instance)
            self.auth = None
            return
        self.transport = transport or RequestsTransport()
        try:
            write = resolve_write_auth(instance)
        except CredentialUnavailable as exc:
            raise WriteNotAvailable("The VSA X API token could not be read.") from exc
        self.auth = (write.username, write.password)

    def write(self, field_id: str, device_id: str, value: str, *, update: bool) -> dict[str, Any]:
        """POST assign (``update=False``) or PUT updateAssigned. Returns the answered ``{Value, ContextItemId}``."""
        if not _DEVICE_ID.fullmatch(device_id or ""):
            raise ValueError("Unsafe device identifier.")
        if not isinstance(value, str) or len(value) > MAX_VALUE or any(ord(c) < 32 for c in value):
            raise ValueError("Unsafe value.")
        path = path_for(self.route, field_id, "updateAssigned" if update else "assign")
        check_egress(self.instance.base_url, "vsa_x", is_fixture=self.instance.is_fixture, resolver=self.resolver)
        body = {"ContextType": "Device", "ContextItemId": device_id, "UseDefaultValue": False, "Value": value}
        try:
            resp = self.transport.send(
                "PUT" if update else "POST",
                f"{self.instance.base_url.rstrip('/')}{path}",
                json=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                auth=self.auth,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise WriteOutcomeUnknown("timeout_or_connection") from exc
        status = int(resp.status_code)
        if 200 <= status < 300:
            try:
                data = (resp.json() or {}).get("Data") or {}
            except ValueError:
                data = {}
            return {"value": str(data.get("Value") or "")[:MAX_VALUE], "device": str(data.get("ContextItemId") or "")}
        if 300 <= status < 400 or status >= 500:
            raise WriteOutcomeUnknown(f"http_{status}", status)
        raise WriteRejected(status)  # 429 included: not applied, the engine backs off before trying again
