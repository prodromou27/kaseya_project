"""VSA2-01..04: expected-inventory uploads and immutable reconciliation runs against a pinned VSA generation.

Every row carries ``customer`` and is DB-checked against its run (migration 0002), so a result can never be
attached to another customer's run, upload, asset or generation.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ExpectedInventoryUpload(models.Model):
    """An uploaded .xlsx/.csv file in private storage. The file is purged after a TTL; metadata is kept."""

    class Format(models.TextChoices):
        XLSX = "xlsx", "Excel workbook"
        CSV = "csv", "CSV"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="onboarding_uploads")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    display_name = models.CharField(max_length=120, help_text="Sanitised original file name (display only).")
    file_format = models.CharField(max_length=4, choices=Format.choices)
    sha256 = models.CharField(max_length=64)
    bytes = models.PositiveIntegerField()
    storage_key = models.CharField(max_length=64, unique=True)
    sheets = models.JSONField(default=list, help_text="[{name, rows, columns}] discovered at upload time.")
    expires_at = models.DateTimeField()
    purged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(storage_key__regex=r"^[0-9a-f]{32}\.upload$"), name="onboarding_storage_key_opaque"
            )
        ]

    def __str__(self) -> str:
        return self.display_name


class MappingTemplate(models.Model):
    """A reusable, customer-scoped column mapping (header text → portal field). Layouts are never assumed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="onboarding_templates")
    name = models.CharField(max_length=120)
    header_row = models.PositiveSmallIntegerField(default=1)
    columns = models.JSONField(help_text="{portal_field: header text}")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["customer", "name"], name="onboarding_template_name_unique")]

    def __str__(self) -> str:
        return self.name


class ReconciliationRun(models.Model):
    """One immutable comparison of an upload (by hash + mapping) with one pinned, complete VSA generation."""

    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="reconciliation_runs")
    upload = models.ForeignKey(ExpectedInventoryUpload, on_delete=models.PROTECT, related_name="runs")
    upload_sha256 = models.CharField(max_length=64)
    upload_name = models.CharField(max_length=120)
    sheet = models.CharField(max_length=64)
    header_row = models.PositiveSmallIntegerField()
    mapping = models.JSONField(help_text="{portal_field: column index} — frozen at request time.")
    mapping_hash = models.CharField(max_length=64)
    logic_version = models.CharField(max_length=32)
    parameters = models.JSONField(default=dict, help_text="Thresholds used for secondary flags.")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    data_basis = models.CharField(max_length=16)
    stale_source_acknowledged = models.BooleanField(default=False)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    error_code = models.CharField(max_length=64, blank=True)
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "-created_at"], name="onboarding_run_cust_idx")]

    def __str__(self) -> str:
        return f"{self.upload_name} vs {self.generation_id} ({self.state})"


class Classification(models.TextChoices):
    MATCHED_CORRECT = "MATCHED_CORRECT", "Matched, correct placement"
    MATCHED_WRONG_GROUP = "MATCHED_WRONG_GROUP", "Matched, wrong group"
    MATCHED_WRONG_SITE = "MATCHED_WRONG_SITE", "Matched, wrong site"
    REVIEW_WRONG_ORGANIZATION = "REVIEW_WRONG_ORGANIZATION", "Review: organisation differs"
    NOT_FOUND_IN_COMPLETE_SNAPSHOT = "NOT_FOUND_IN_COMPLETE_SNAPSHOT", "Not found in complete snapshot"
    AMBIGUOUS = "AMBIGUOUS", "Ambiguous: needs review"
    DUPLICATE_INPUT = "DUPLICATE_INPUT", "Duplicate input row"
    INVALID_INPUT = "INVALID_INPUT", "Invalid input row"


class ReconciliationResult(models.Model):
    """One expected row (``kind=expected``) or one VSA device absent from the accepted rows (``kind=unexpected``).

    ``classification`` and ``evidence`` are written once by the engine. A reviewer decision is stored beside them
    (``reviewed_*``) — the original machine result is never overwritten.
    """

    class Kind(models.TextChoices):
        EXPECTED = "expected", "Expected row"
        UNEXPECTED = "unexpected", "Unexpected VSA asset"

    class ReviewState(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending", "Pending review"
        DECIDED = "decided", "Decided"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ReconciliationRun, on_delete=models.PROTECT, related_name="results")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    row_number = models.PositiveIntegerField(null=True, blank=True, help_text="Sheet row (expected rows).")
    input = models.JSONField(default=dict, help_text="Mapped input values as uploaded (text).")
    classification = models.CharField(max_length=32, choices=Classification.choices, blank=True)
    flags = models.JSONField(default=list)
    evidence = models.JSONField(default=dict)
    candidate_asset_ids = models.JSONField(default=list)
    asset = models.ForeignKey("inventory.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    actual = models.JSONField(default=dict, help_text="Matched device placement/hostname from the pinned snapshot.")
    pending_review_row = models.PositiveIntegerField(
        null=True, blank=True, help_text="Unexpected device that is a candidate of an unresolved ambiguous row."
    )
    review_state = models.CharField(max_length=16, choices=ReviewState.choices, default=ReviewState.NOT_REQUIRED)
    reviewed_classification = models.CharField(max_length=32, choices=Classification.choices, blank=True)
    reviewed_asset = models.ForeignKey(
        "inventory.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["kind", "row_number", "id"]
        indexes = [
            models.Index(fields=["run", "kind", "classification"], name="onboarding_res_run_cls_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="unexpected") | (Q(row_number__isnull=False) & ~Q(classification="")),
                name="onboarding_expected_row_classified",
            )
        ]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.kind}:{self.row_number}"

    @property
    def effective_classification(self) -> str:
        return self.reviewed_classification or self.classification
