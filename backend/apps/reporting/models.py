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
