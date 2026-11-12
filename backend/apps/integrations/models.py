from __future__ import annotations

import uuid
from decimal import Decimal
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from .urlpolicy import validate_connector_base_url


class IntegrationInstance(models.Model):
    """A configured, read-only vendor connection. Holds a *reference* to a secret, never the secret."""

    class Provider(models.TextChoices):
        VSA_X = "vsa_x", "Kaseya VSA X"
        ITGLUE = "itglue", "IT Glue"
        AUTOTASK = "autotask", "Autotask PSA"

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"
        COMPLETED = "completed", "Completed"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    provider = models.CharField(max_length=16, choices=Provider.choices)
    base_url = models.CharField(max_length=500)
    region = models.CharField(max_length=32, blank=True)
    credential_ref = models.CharField(
        max_length=200,
        blank=True,
        validators=[RegexValidator(r"^[A-Za-z0-9_./:-]*$", "Secret reference name only (no secret values).")],
        help_text="Name of the secret in the approved secret store, e.g. 'vault:kv/portal/vsa-prod'.",
    )
    enabled = models.BooleanField(default=False)
    verify_tls = models.BooleanField(default=True, editable=False)
    max_rps = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.50"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("20"))],
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IDLE)
    is_fixture = models.BooleanField(
        default=False, help_text="True for demo/fixture-backed instances. Never mixed with live data."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "name"]
        constraints = [
            # TLS verification can never be disabled (AGENTS.md: do not disable TLS verification).
            models.CheckConstraint(condition=Q(verify_tls=True), name="integrations_verify_tls_always_true"),
            models.CheckConstraint(condition=Q(base_url__startswith="https://"), name="integrations_https_only"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.provider})"

    def clean(self) -> None:
        if self.is_fixture:
            # Fixture instances never touch the network. Require an RFC 2606 reserved `.invalid` host so a
            # fixture record can never be pointed at a real endpoint.
            host = urlsplit(self.base_url or "").hostname or ""
            if not (self.base_url or "").startswith("https://") or not host.endswith(".invalid"):
                raise ValidationError({"base_url": "Fixture instances must use an https://<name>.invalid URL."})
            if self.credential_ref:
                raise ValidationError({"credential_ref": "Fixture instances must not reference credentials."})
            return
        try:
            self.base_url = validate_connector_base_url(self.base_url, self.provider)
        except ValidationError as exc:
            raise ValidationError({"base_url": exc.messages}) from exc
