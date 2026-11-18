"""CFA: confirm the custom field write route on ONE authorised test workstation before writes are enabled.

The documentation names two forms (``/api/v3/customfields/{id}/…`` in the headings, ``/api/v3/automation/customfields/
{id}/…`` in the samples). This writes the given value to the given device with the heading form, falls back to the
sample form only when VSA X answers 404 (route does not exist, nothing written), reads the value back and records the
form that worked on the integration. Nothing else is tried; no other device is touched.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.audit.services import record_event
from apps.customfields import definitions
from apps.customfields.models import CustomFieldDefinition
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import WRITE_REF
from apps.integrations.vsa.adapter import VsaXAdapter
from apps.integrations.vsa.cf_writer import ROUTES, VsaCustomFieldWriter, WriteOutcomeUnknown, WriteRejected
from apps.inventory.models import Asset


class Command(BaseCommand):
    help = "Validate the VSA X custom field write route on one authorised test workstation (writes one value)."

    def add_arguments(self, parser):
        parser.add_argument("--integration", required=True)
        parser.add_argument("--device", required=True, help="VSA X device identifier (GUID) of the TEST workstation")
        parser.add_argument("--field", required=True, help="VSA X custom field ID")
        parser.add_argument("--value", required=True)
        parser.add_argument("--confirm-test-device", action="store_true")

    def handle(self, *args, **o):
        if not o["confirm_test_device"]:
            raise CommandError("This writes to VSA X. Re-run with --confirm-test-device for an authorised test device.")
        if not settings.VSA_CUSTOM_FIELD_WRITES_ENABLED:
            raise CommandError("Set VSA_CUSTOM_FIELD_WRITES_ENABLED=true on this server first.")
        try:
            instance = IntegrationInstance.objects.get(pk=o["integration"], provider="vsa_x")
        except (IntegrationInstance.DoesNotExist, ValueError) as exc:
            raise CommandError("Unknown VSA X integration.") from exc
        if not instance.is_fixture and not WRITE_REF.fullmatch(instance.write_credential_ref or ""):
            raise CommandError("Configure the separate write token (env:VSA_WRITE_<NAME>) first.")
        if not Asset.objects.filter(integration_instance=instance, external_id=o["device"]).exists():
            raise CommandError("The device is not in this integration's synced inventory.")
        adapter = VsaXAdapter(instance)
        definitions.refresh(instance, adapter)
        try:
            field = CustomFieldDefinition.objects.get(integration_instance=instance, external_id=str(o["field"]))
        except CustomFieldDefinition.DoesNotExist as exc:
            raise CommandError("VSA X does not list that custom field.") from exc
        ok, reason = definitions.device_capable(field)
        if not ok:
            raise CommandError(f"Field not usable on devices: {reason}.")
        value = definitions.normalise(field.type, o["value"])
        device = o["device"]
        assigned = any(
            str(r.get("ContextItemId")) == device for r in adapter.custom_field_device_usage(field.external_id, device)
        )
        self.stdout.write(
            f"Device-level assignment exists: {assigned}; sending {'PUT update' if assigned else 'POST assign'}."
        )
        worked = None
        for route in ROUTES:
            writer = VsaCustomFieldWriter(instance, route=route, check_gates=False)
            try:
                writer.write(field.external_id, device, value, update=assigned)
                worked = route
                break
            except WriteRejected as exc:
                self.stdout.write(f"  /api/v3/{route}/… answered HTTP {exc.status}.")
                if exc.status != 404:
                    break
            except WriteOutcomeUnknown as exc:
                self.stdout.write(
                    f"  /api/v3/{route}/… gave no definite answer ({exc.code}); checking by reading back."
                )
                worked = route
                break
        rows = adapter.custom_field_device_usage(field.external_id, device)
        observed = next((str(r.get("Value")) for r in rows if str(r.get("ContextItemId")) == device), None)
        verified = worked is not None and definitions.same(field.type, observed, value)
        record_event(
            action="custom_field.route_validated" if verified else "custom_field.route_validation_failed",
            outcome="success" if verified else "failure",
            target_type="integration",
            target_id=str(instance.id),
            actor_label="manage.py vsa_custom_field_validate",
            metadata={"route": worked, "field_id": field.external_id, "device": device, "observed": observed},
        )
        if not verified:
            raise CommandError(f"Not confirmed: read back {observed!r}. No route recorded; writes stay unavailable.")
        instance.custom_field_write_route, instance.custom_field_route_validated_at = worked, timezone.now()
        instance.save(update_fields=["custom_field_write_route", "custom_field_route_validated_at"])
        self.stdout.write(self.style.SUCCESS(f"Confirmed: /api/v3/{worked}/{{id}}/… wrote {value!r}. Route recorded."))
