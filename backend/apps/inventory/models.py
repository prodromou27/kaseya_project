from __future__ import annotations

import uuid

from django.db import models


class Asset(models.Model):
    """Stable identity of a source device. Descriptive data lives in per-generation ``AssetObservation`` rows.

    ``(integration_instance, external_id)`` is unique: a vendor ID is never re-attributed to another customer
    (a conflicting record is quarantined instead).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="assets")
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.PROTECT, related_name="assets"
    )
    external_id = models.CharField(max_length=128)
    active = models.BooleanField(default=True, help_text="False once absent from a complete, published inventory.")
    last_generation = models.ForeignKey(
        "integrations.DatasetGeneration", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration_instance", "external_id"], name="inventory_asset_source_unique"
            )
        ]
        indexes = [models.Index(fields=["customer", "active"], name="inventory_asset_cust_act_idx")]

    def __str__(self) -> str:
        return f"{self.integration_instance_id}:{self.external_id}"


class AssetObservation(models.Model):
    class SoftwareStatus(models.TextChoices):
        COLLECTED = "collected", "Collected"
        NOT_COLLECTED = "not_collected", "Not collected (section absent)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="observations")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="asset_observations"
    )
    hostname = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)
    device_type = models.CharField(max_length=64, blank=True)
    group_name = models.CharField(max_length=255, blank=True)
    site_external_id = models.CharField(max_length=64, blank=True)
    organization_external_id = models.CharField(max_length=64)
    computer_id = models.CharField(max_length=64, blank=True)
    client_version = models.CharField(max_length=64, blank=True)
    last_seen_online = models.DateTimeField(null=True, blank=True)
    os_name = models.CharField(max_length=255, blank=True)
    os_version = models.CharField(max_length=64, blank=True)
    manufacturer = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    tags = models.JSONField(default=list, blank=True)
    software_status = models.CharField(max_length=16, choices=SoftwareStatus.choices)
    software_count = models.PositiveIntegerField(null=True, blank=True)
    collected_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["asset", "generation"], name="inventory_observation_asset_gen_unique")
        ]
        indexes = [
            models.Index(fields=["generation", "hostname"], name="inventory_obs_gen_host_idx"),
            models.Index(fields=["customer", "last_seen_online"], name="inventory_obs_cust_seen"),
            models.Index(fields=["generation", "group_name"], name="inventory_obs_gen_group"),
        ]

    def __str__(self) -> str:
        return f"{self.hostname} @ {self.generation_id}"
