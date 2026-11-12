from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class ReportRun(models.Model):
    """An asynchronous, customer-scoped report generation request.

    The Celery job receives only ``ReportRun.id``; the customer is always re-resolved from this row and the
    requester's authorisation is re-checked inside the worker before any data is read.
    """

    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="report_runs")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    report_type = models.CharField(max_length=64)
    format = models.CharField(max_length=8, default="csv")
    filters = models.JSONField(default=dict, blank=True)
    filters_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    row_count = models.PositiveIntegerField(null=True, blank=True)
    as_of_generation_ids = models.JSONField(default=dict, blank=True)
    regenerated_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="regenerations",
        help_text="Set when this run reproduces an earlier run from the same pinned snapshot.",
    )
    data_basis = models.CharField(max_length=32, default="portal_internal", help_text="fixture|live|portal_internal")
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "-created_at"], name="reporting_run_cust_created_idx")]

    def __str__(self) -> str:
        return f"{self.report_type} {self.customer_id} {self.state}"


class ReportArtifact(models.Model):
    """A generated file in private storage. ``storage_key`` is an opaque name, never a client-visible path."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report_run = models.OneToOneField(ReportRun, on_delete=models.PROTECT, related_name="artifact")
    storage_key = models.CharField(max_length=128, unique=True)
    format = models.CharField(max_length=8)
    sha256 = models.CharField(max_length=64)
    bytes = models.PositiveBigIntegerField()
    expires_at = models.DateTimeField()
    purged_at = models.DateTimeField(null=True, blank=True)
    encryption_key_ref = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(storage_key__regex=r"^[0-9a-f]{32}\.[a-z]{3,4}$"), name="reporting_storage_key_opaque"
            )
        ]

    def __str__(self) -> str:
        return self.storage_key


class SavedView(models.Model):
    """A named, validated filter set for an in-app view. Customer-scoped; owner-private unless shared."""

    class ViewType(models.TextChoices):
        ASSETS = "assets", "Assets"
        SOFTWARE = "software", "Software versions"
        OS_UPDATES = "os_updates", "Windows updates"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="saved_views")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=120)
    view_type = models.CharField(max_length=16, choices=ViewType.choices)
    filters = models.JSONField(default=dict)
    shared = models.BooleanField(default=False, help_text="Visible to everyone with read access to the customer.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "owner", "view_type", "name"], name="reporting_view_name_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name


class ReportDefinition(models.Model):
    """A saved report request (template key + validated filters + format) that schedules execute."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="report_definitions")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=120)
    report_type = models.CharField(max_length=64)
    format = models.CharField(max_length=8, default="csv")
    filters = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ReportSchedule(models.Model):
    """Recurring generation of a definition. Delivery is in-portal only (DEC-09: no e-mail until approved)."""

    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    definition = models.ForeignKey(ReportDefinition, on_delete=models.PROTECT, related_name="schedules")
    frequency = models.CharField(max_length=8, choices=Frequency.choices)
    time_of_day = models.TimeField(help_text="Local time in ``timezone``.")
    weekday = models.PositiveSmallIntegerField(null=True, blank=True, help_text="0=Monday (weekly only).")
    day_of_month = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1-28 (monthly only).")
    timezone = models.CharField(max_length=64, default="UTC")
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_run_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(day_of_month__isnull=True) | Q(day_of_month__gte=1, day_of_month__lte=28),
                name="reporting_schedule_day_of_month_range",
            ),
            models.CheckConstraint(
                condition=Q(weekday__isnull=True) | Q(weekday__lte=6), name="reporting_schedule_weekday_range"
            ),
        ]
        indexes = [models.Index(fields=["enabled", "next_run_at"], name="reporting_sched_due_idx")]

    def __str__(self) -> str:
        return f"{self.definition_id} {self.frequency}"


class ScheduledExecution(models.Model):
    """One slot of a schedule. ``(schedule, slot_at)`` is unique: duplicate dispatches are suppressed by the DB."""

    class State(models.TextChoices):
        STARTED = "started", "Report requested"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.ForeignKey(ReportSchedule, on_delete=models.PROTECT, related_name="executions")
    slot_at = models.DateTimeField()
    state = models.CharField(max_length=8, choices=State.choices)
    reason = models.CharField(max_length=64, blank=True)
    report_run = models.OneToOneField(
        ReportRun, null=True, blank=True, on_delete=models.PROTECT, related_name="scheduled_execution"
    )
    delivered_to = models.JSONField(default=list, help_text="User IDs with access at execution time.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-slot_at"]
        constraints = [models.UniqueConstraint(fields=["schedule", "slot_at"], name="reporting_one_execution_per_slot")]

    def __str__(self) -> str:
        return f"{self.schedule_id}@{self.slot_at:%Y-%m-%dT%H:%M}"
