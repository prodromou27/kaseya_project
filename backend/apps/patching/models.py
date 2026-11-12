"""OS update observations from VSA X (P2-01). Read-only source data; never patch orchestration.

Status vocabulary per device (never collapse to a false zero):

* ``collected``      — section present in the source response (an empty list is a real zero).
* ``not_collected``  — section absent from the response for a Windows device.
* ``not_supported``  — device type is not Windows; OS update data is not expected.
* ``not_requested``  — InstalledUpdates collection disabled (budget 0) or not reached this run (budget rotation).
* ``failed``         — the per-device detail call failed for this device.
* ``carried_forward``— (InstalledUpdates only) not fetched this run; rows copied from the last successful
  collection, whose timestamp is kept in ``installed_collected_at``.
"""

from __future__ import annotations

import uuid

from django.db import models


class UpdateStatus(models.TextChoices):
    COLLECTED = "collected", "Collected"
    NOT_COLLECTED = "not_collected", "Not collected (section absent)"
    NOT_SUPPORTED = "not_supported", "Not supported (non-Windows)"
    NOT_REQUESTED = "not_requested", "Not requested (disabled or outside budget)"
    FAILED = "failed", "Collection failed"
    CARRIED_FORWARD = "carried_forward", "Carried forward from an earlier collection"


class OsUpdate(models.Model):
    """Normalised update identity keyed by the vendor UpdateId + RevisionNumber. Metadata only."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    update_id = models.CharField(max_length=128)
    revision_number = models.IntegerField(null=True, blank=True)
    kb_article = models.CharField(max_length=16, blank=True)
    title = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=32, blank=True)
    category = models.CharField(max_length=64, blank=True)
    release_date = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["update_id", "revision_number"], name="patching_osupdate_identity", nulls_distinct=False
            )
        ]
        indexes = [models.Index(fields=["kb_article"], name="patching_osupdate_kb_idx")]

    def __str__(self) -> str:
        return f"KB{self.kb_article}" if self.kb_article else self.update_id


class PatchObservation(models.Model):
    """Per device, per generation: which OS update sections were obtained, and their counts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    observation = models.OneToOneField(
        "inventory.AssetObservation", on_delete=models.PROTECT, related_name="patch_observation"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey("inventory.Asset", on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="patch_observations"
    )
    update_counts = models.JSONField(null=True, blank=True, help_text="Source 'Updates' object; null if absent.")
    available_status = models.CharField(max_length=16, choices=UpdateStatus.choices)
    available_count = models.PositiveIntegerField(null=True, blank=True)
    installed_status = models.CharField(max_length=16, choices=UpdateStatus.choices)
    installed_count = models.PositiveIntegerField(null=True, blank=True)
    installed_collected_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["generation", "available_status"], name="patching_obs_gen_avail_idx"),
            models.Index(fields=["customer", "generation"], name="patching_obs_cust_gen_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.asset_id}@{self.generation_id}"


class DeviceOsUpdate(models.Model):
    class State(models.TextChoices):
        AVAILABLE = "available", "Available (not installed)"
        INSTALLED = "installed", "Installed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey("inventory.Asset", on_delete=models.PROTECT, related_name="os_updates")
    patch_observation = models.ForeignKey(PatchObservation, on_delete=models.PROTECT, related_name="updates")
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="device_os_updates"
    )
    os_update = models.ForeignKey(OsUpdate, on_delete=models.PROTECT, related_name="device_rows")
    state = models.CharField(max_length=10, choices=State.choices)
    severity = models.CharField(max_length=32, blank=True)
    category = models.CharField(max_length=64, blank=True)
    cvss_score = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    cve_codes = models.JSONField(default=list, blank=True)
    installed_at_raw = models.CharField(
        max_length=40, blank=True, help_text="Vendor value verbatim; documented without timezone."
    )
    installed_by_agent = models.BooleanField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patch_observation", "os_update", "state"], name="patching_device_update_unique"
            )
        ]
        indexes = [
            models.Index(fields=["customer", "generation", "state", "os_update"], name="patching_dou_cust_gen_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.asset_id} {self.os_update_id} {self.state}"
