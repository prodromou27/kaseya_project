"""CFA: confirm the custom field write route on ONE authorised test workstation (command-line form).

The same check is available in the portal: Settings → Integrations → Edit → "Validate on a test workstation".
See ``apps.customfields.validation``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.customfields.validation import ValidationFailed, validate_route
from apps.integrations.models import IntegrationInstance


class Command(BaseCommand):
    help = "Validate the VSA X custom field write route on one authorised test workstation (writes one value)."

    def add_arguments(self, parser):
        parser.add_argument("--integration", required=True)
        parser.add_argument("--device", required=True, help="VSA X device ID (GUID) or hostname of the TEST device")
        parser.add_argument("--field", required=True, help="VSA X custom field ID")
        parser.add_argument("--value", required=True)
        parser.add_argument("--confirm-test-device", action="store_true")

    def handle(self, *args, **o):
        if not o["confirm_test_device"]:
            raise CommandError("This writes to VSA X. Re-run with --confirm-test-device for an authorised test device.")
        try:
            instance = IntegrationInstance.objects.get(pk=o["integration"], provider="vsa_x")
        except (IntegrationInstance.DoesNotExist, ValueError) as exc:
            raise CommandError("Unknown VSA X integration.") from exc
        try:
            result = validate_route(
                instance,
                device=o["device"],
                field_id=o["field"],
                value=o["value"],
                actor_label="manage.py vsa_custom_field_validate",
                log=lambda msg: self.stdout.write(f"  {msg}"),
            )
        except ValidationFailed as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Confirmed: /api/v3/{result['route']}/{{id}}/… wrote {result['value']!r}. Route recorded."
            )
        )
