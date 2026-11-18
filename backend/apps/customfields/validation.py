"""CFA: confirm the custom field write route on ONE authorised test workstation before writes are used.

The documentation names two forms (``/api/v3/customfields/{id}/…`` in the headings, ``/api/v3/automation/customfields/
{id}/…`` in the samples). This writes the given value to the given device with the heading form, falls back to the
sample form only when VSA X answers 404 (route does not exist, nothing written), reads the value back and records the
form that worked on the integration. Nothing else is tried; no other device is touched.

Used by the portal (Settings → Integrations, super admin) and by ``manage.py vsa_custom_field_validate``.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.audit.services import record_event
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import can_write
from apps.integrations.vsa.adapter import VsaXAdapter
from apps.integrations.vsa.cf_writer import (
    ROUTES,
    VsaCustomFieldWriter,
    WriteNotAvailable,
    WriteOutcomeUnknown,
    WriteRejected,
)
from apps.inventory.models import Asset, AssetObservation

from . import definitions
from .models import CustomFieldDefinition


class ValidationFailed(Exception):
    """Safe message for the administrator; no secret or response body."""


def find_device(instance: IntegrationInstance, device: str) -> str:
    """The VSA X device identifier for a GUID or a hostname in this integration's synced inventory (exact only)."""
    device = (device or "").strip()
    if not device:
        raise ValidationFailed("Enter the test workstation's name or VSA X device ID.")
    if Asset.objects.filter(integration_instance=instance, external_id=device, active=True).exists():
        return device
    ids = set(
        AssetObservation.objects.filter(
            asset__integration_instance=instance, asset__active=True, hostname__iexact=device
        ).values_list("asset__external_id", flat=True)
    )
    if len(ids) > 1:
        raise ValidationFailed("More than one device has that name. Use its VSA X device ID instead.")
    if not ids:
        raise ValidationFailed("That device is not in this integration's synced inventory.")
    return ids.pop()


def validate_route(
    instance: IntegrationInstance,
    *,
    device: str,
    field_id: str,
    value: str,
    actor: Any = None,
    actor_label: str = "",
    request: Any = None,
    log: Any = None,
) -> dict[str, Any]:
    """Write once, read back, record the route. Returns ``{route, field, device, value, observed}``."""
    say = log or (lambda _msg: None)
    if not settings.VSA_CUSTOM_FIELD_WRITES_ENABLED:
        raise ValidationFailed("Writing custom fields is switched off on this server (emergency stop).")
    if instance.provider != IntegrationInstance.Provider.VSA_X or not instance.enabled:
        raise ValidationFailed("The VSA X integration is not enabled.")
    if not instance.is_fixture and not can_write(instance):
        raise ValidationFailed("Enter the VSA X API token first.")
    device_id = find_device(instance, device)
    adapter = VsaXAdapter(instance)
    definitions.refresh(instance, adapter)
    try:
        field = CustomFieldDefinition.objects.get(integration_instance=instance, external_id=str(field_id).strip())
    except CustomFieldDefinition.DoesNotExist as exc:
        raise ValidationFailed("VSA X does not list that custom field.") from exc
    ok, reason = definitions.device_capable(field)
    if not ok:
        raise ValidationFailed(f"That field cannot be used on devices: {reason}.")
    try:
        normalised = definitions.normalise(field.type, value)
    except Exception as exc:  # serializers.ValidationError / ValueError with a safe message
        raise ValidationFailed(f"The test value is not valid for a {field.type} field.") from exc
    assigned = any(
        str(r.get("ContextItemId")) == device_id
        for r in adapter.custom_field_device_usage(field.external_id, device_id)
    )
    say(f"Device-level assignment exists: {assigned}; sending {'PUT update' if assigned else 'POST assign'}.")
    worked, answers = None, []
    for route in ROUTES:
        try:
            VsaCustomFieldWriter(instance, route=route, check_gates=False).write(
                field.external_id, device_id, normalised, update=assigned
            )
            worked = route
            break
        except WriteNotAvailable as exc:
            raise ValidationFailed(str(exc)) from exc
        except WriteRejected as exc:
            answers.append(f"/api/v3/{route}/… answered HTTP {exc.status}")
            say(answers[-1])
            if exc.status != 404:
                break
        except WriteOutcomeUnknown as exc:
            say(f"/api/v3/{route}/… gave no definite answer ({exc.code}); checking by reading back.")
            worked = route
            break
    rows = adapter.custom_field_device_usage(field.external_id, device_id)
    observed = next((str(r.get("Value")) for r in rows if str(r.get("ContextItemId")) == device_id), None)
    verified = worked is not None and definitions.same(field.type, observed, normalised)
    record_event(
        action="custom_field.route_validated" if verified else "custom_field.route_validation_failed",
        outcome="success" if verified else "failure",
        actor=actor,
        actor_label=actor_label,
        target_type="integration",
        target_id=str(instance.id),
        request=request,
        metadata={"route": worked, "field_id": field.external_id, "device": device_id, "observed": observed},
    )
    if not verified:
        detail = "; ".join(answers) or f"read back {observed!r}"
        raise ValidationFailed(f"Not confirmed ({detail}). No route recorded; writes stay unavailable.")
    instance.custom_field_write_route, instance.custom_field_route_validated_at = worked, timezone.now()
    instance.save(update_fields=["custom_field_write_route", "custom_field_route_validated_at"])
    return {
        "route": worked,
        "field": field.name,
        "field_id": field.external_id,
        "device": device_id,
        "value": normalised,
        "observed": observed,
    }
