"""CFA: VSA X custom field assignment (ADR-031) - definitions, jobs and per-device results."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class CustomFieldDefinition(models.Model):
    """A custom field as listed by ``GET /api/v3/customFields`` for one integration, plus the portal's edit setting."""

    class Type(models.TextChoices):
        TEXT = "Text", "Text"
        NUMBER = "Number", "Number"
        BOOLEAN = "Boolean", "Boolean"
        DATE = "Date", "Date"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.PROTECT, related_name="custom_field_definitions"
    )
    external_id = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=1000, blank=True)
    type = models.CharField(max_length=16, blank=True)
    default_value = models.CharField(max_length=255, blank=True)
    is_read_only = models.BooleanField(default=False)
    contexts = models.JSONField(default=list)
    expiration_date = models.DateTimeField(null=True, blank=True)
    present = models.BooleanField(default=True, help_text="False once VSA X no longer lists the field.")
    fetched_at = models.DateTimeField()
    # Portal settings (super admin, audited). A field is never editable unless explicitly allowed here.
    portal_writable = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    settings_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    settings_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "external_id"]
        constraints = [
            models.UniqueConstraint(fields=["integration_instance", "external_id"], name="customfields_def_unique")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.external_id})"


class AssignmentJob(models.Model):
    """One requested change: one field, one value (or one per device), for an immutable list of devices."""

    class State(models.TextChoices):
        DRAFT = "draft", "Draft (review matches)"
        PREVIEWING = "previewing", "Reading current values"
        PREVIEWED = "previewed", "Preview ready"
        AWAITING_APPROVAL = "awaiting_approval", "Waiting for approval"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Approval rejected"

    class Source(models.TextChoices):
        SELECTION = "selection", "Selected devices"
        LIST = "list", "Pasted list"
        IMPORT = "import", "Imported file"
        DEVICE = "device", "Device page"
        RETRY = "retry", "Retry of failed devices"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.PROTECT, related_name="+"
    )
    field = models.ForeignKey(CustomFieldDefinition, on_delete=models.PROTECT, related_name="jobs")
    value = models.CharField(max_length=255, blank=True, help_text="Requested value (unless set per device).")
    per_device_values = models.BooleanField(default=False)
    # CFA-10: placeholder mode - only devices with no value get the value; any existing value is left unchanged.
    only_if_empty = models.BooleanField(default=False)
    source = models.CharField(max_length=12, choices=Source.choices)
    source_filename = models.CharField(max_length=255, blank=True)
    retry_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    previewed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    approval_required = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    counts = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["customer", "-created_at"], name="customfields_job_cust_idx")]

    def __str__(self) -> str:
        return f"job {self.id} {self.field_id} {self.state}"


class AssignmentItem(models.Model):
    """One input line (or selected device): how it matched, what the preview found and what happened."""

    class Match(models.TextChoices):
        MATCHED = "matched", "Matched"
        NOT_FOUND = "not_found", "Not found"
        MULTIPLE = "multiple", "Multiple matches"
        DUPLICATE = "duplicate", "Duplicate input"
        INVALID = "invalid", "Invalid identifier"
        OTHER_CUSTOMER = "other_customer", "Outside the selected customer"
        UNSUPPORTED = "unsupported", "Unsupported device"

    class Action(models.TextChoices):
        NONE = "", "Not previewed"
        ASSIGN = "assign", "Assign"
        UPDATE = "update", "Update"
        SKIP = "skip", "Skip - already correct"
        BLOCKED = "blocked", "Blocked"
        REVIEW = "review", "Requires review"

    class Result(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        VERIFIED = "verified", "Verified success"
        ALREADY_CORRECT = "already_correct", "Already correct"
        FAILED = "failed", "Failed"
        VERIFICATION_PENDING = "verification_pending", "Verification pending"
        VERIFICATION_FAILED = "verification_failed", "Verification failed"
        UNKNOWN = "unknown", "Unknown outcome"
        SKIPPED = "skipped", "Skipped"
        CANCELLED = "cancelled", "Cancelled"
        NOT_RUN = "not_run", "Not run"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(AssignmentJob, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField()
    input_identifier = models.CharField(max_length=255, blank=True)
    input_kind = models.CharField(max_length=16, blank=True)
    input_row = models.PositiveIntegerField(null=True, blank=True)
    match_status = models.CharField(max_length=16, choices=Match.choices)
    match_note = models.CharField(max_length=255, blank=True)
    candidates = models.JSONField(default=list, blank=True)
    asset = models.ForeignKey("inventory.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    device_external_id = models.CharField(max_length=64, blank=True)
    hostname = models.CharField(max_length=255, blank=True)
    site = models.CharField(max_length=255, blank=True)
    group = models.CharField(max_length=255, blank=True)
    requested_value = models.CharField(max_length=255, blank=True)
    included = models.BooleanField(default=True)
    current_value = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 - null = not read
    current_source = models.CharField(max_length=12, blank=True)  # device | inherited | none | unknown
    device_assigned = models.BooleanField(null=True)
    action = models.CharField(max_length=10, choices=Action.choices, blank=True)
    action_note = models.CharField(max_length=255, blank=True)
    result = models.CharField(max_length=24, choices=Result.choices, default=Result.PENDING)
    final_value = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001 - null = not read
    http_status = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["job", "position"]
        indexes = [models.Index(fields=["job", "result"], name="customfields_item_job_res")]

    def __str__(self) -> str:
        return f"{self.input_identifier or self.hostname}: {self.match_status}/{self.action}/{self.result}"
