from __future__ import annotations

import uuid
from decimal import Decimal
from urllib.parse import urlsplit

from django.conf import settings
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
    installed_updates_budget = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(3000)],
        help_text="Max per-device GET /api/v3/assets/:id calls per sync for InstalledUpdates (0 = disabled). "
        "Documented limit is 3600 requests/hour per token+endpoint.",
    )
    applied_policies_budget = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(3000)],
        help_text="Max per-device GET /api/v3/devices/:id/appliedpolicies calls per sync (0 = disabled). "
        "Documented limit is 3600 requests/hour.",
    )
    notifications_budget = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(3000)],
        help_text="Max per-device GET /api/v3/devices/:id/notifications calls per sync (0 = disabled).",
    )
    custom_fields_budget = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(3000)],
        help_text="Max per-device GET /api/v3/devices/:id/customfields calls per sync (0 = disabled). Used only for "
        "customers with approved custom field names.",
    )
    # VSA1-01: result of the last administrator connection test (no credentials or raw bodies are stored).
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_outcome = models.CharField(max_length=32, blank=True)
    last_test_result = models.JSONField(default=dict, blank=True)
    is_fixture = models.BooleanField(
        default=False, help_text="True for demo/fixture-backed instances. Never mixed with live data."
    )
    # API token entered in the portal by a super admin: Fernet ciphertext only (apps.integrations.secrets). The key is a
    # host secret file, not in the DB. Never serialised, logged or audited. Cleared when the base URL changes.
    credential_ciphertext = models.TextField(blank=True, default="", editable=False)
    credential_set_at = models.DateTimeField(null=True, blank=True, editable=False)
    credential_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
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


class DatasetGeneration(models.Model):
    """One complete, validated snapshot of a dataset for one customer from one integration instance.

    Rows are staged under a new generation; only after every page is fetched and consistency checks pass is
    the generation atomically flipped to ``is_current`` (one current generation per scope, DB-enforced). A
    failed or interrupted sync leaves the previous current generation untouched.
    """

    class State(models.TextChoices):
        STAGED = "staged", "Staged"
        PUBLISHED = "published", "Published (current)"
        SUPERSEDED = "superseded", "Superseded"
        DISCARDED = "discarded", "Discarded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="generations")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="generations")
    mapping = models.ForeignKey("customers.CustomerSourceMapping", on_delete=models.PROTECT, related_name="generations")
    dataset = models.CharField(max_length=32)
    state = models.CharField(max_length=16, choices=State.choices, default=State.STAGED)
    is_current = models.BooleanField(default=False)
    data_basis = models.CharField(max_length=16, help_text="fixture | live")
    row_count = models.PositiveIntegerField(default=0)
    software_row_count = models.PositiveIntegerField(default=0)
    source_total_count = models.PositiveIntegerField(null=True, blank=True)
    hierarchy_status = models.CharField(max_length=16, default="not_collected", help_text="sites/groups/devices crawl")
    device_list_count = models.PositiveIntegerField(null=True, blank=True)
    devices_without_asset = models.PositiveIntegerField(null=True, blank=True)
    validation_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["integration_instance", "customer", "dataset"],
                condition=Q(is_current=True),
                name="integrations_one_current_generation_per_scope",
            ),
            models.CheckConstraint(
                condition=~Q(is_current=True) | Q(state="published"), name="integrations_current_is_published"
            ),
        ]
        indexes = [models.Index(fields=["customer", "dataset", "is_current"], name="integrations_gen_cur_idx")]

    def __str__(self) -> str:
        return f"{self.dataset}:{self.id} ({self.state})"


class SyncRun(models.Model):
    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        PARTIAL = "partial", "Partial (resumable)"
        FAILED = "failed", "Failed"
        COMPLETED = "completed", "Completed"

    ACTIVE_STATES = (State.QUEUED, State.RUNNING, State.PARTIAL)

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCHEDULE = "schedule", "Schedule"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="sync_runs")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="sync_runs")
    mapping = models.ForeignKey("customers.CustomerSourceMapping", on_delete=models.PROTECT, related_name="sync_runs")
    dataset = models.CharField(max_length=32)
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    trigger = models.CharField(max_length=16, choices=Trigger.choices, default=Trigger.MANUAL)
    requested_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    idempotency_key = models.CharField(max_length=128, unique=True)
    generation = models.OneToOneField(
        DatasetGeneration, null=True, blank=True, on_delete=models.PROTECT, related_name="sync_run"
    )
    next_skip = models.PositiveIntegerField(default=0, help_text="Checkpoint: next $skip to fetch.")
    pages_fetched = models.PositiveIntegerField(default=0)
    fetched_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    quarantined_count = models.PositiveIntegerField(default=0)
    source_total_count = models.PositiveIntegerField(null=True, blank=True)
    installed_updates_requested = models.PositiveIntegerField(default=0)
    applied_policies_requested = models.PositiveIntegerField(default=0)
    notifications_requested = models.PositiveIntegerField(default=0)
    custom_fields_requested = models.PositiveIntegerField(default=0)
    initial_total_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="TotalCount reported by the first page; every later page must match."
    )
    api_requests = models.PositiveIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One active run per (instance, customer, dataset) scope.
            models.UniqueConstraint(
                fields=["integration_instance", "customer", "dataset"],
                condition=Q(state__in=["queued", "running", "partial"]),
                name="integrations_one_active_run_per_scope",
            ),
            # Per-instance concurrency cap: one run actively calling a vendor instance at a time.
            models.UniqueConstraint(
                fields=["integration_instance"],
                condition=Q(state="running"),
                name="integrations_one_running_run_per_instance",
            ),
        ]
        indexes = [
            models.Index(
                fields=["integration_instance", "customer", "dataset", "-created_at"], name="integrations_run_scope_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.dataset} {self.customer_id} {self.state}"


class SyncQuarantine(models.Model):
    """Source records that could not be safely attributed or validated. Visible to super admins only."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sync_run = models.ForeignKey(SyncRun, on_delete=models.PROTECT, related_name="quarantined")
    integration_instance = models.ForeignKey(IntegrationInstance, on_delete=models.PROTECT, related_name="+")
    external_id = models.CharField(max_length=128, blank=True)
    external_org_id = models.CharField(max_length=128, blank=True)
    reason = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict, help_text="Minimal redacted identifiers only.")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["integration_instance", "reason"], name="integrations_quar_reason_idx")]

    def __str__(self) -> str:
        return f"{self.external_id} ({self.reason})"


class SyncSchedule(models.Model):
    """Periodic read-only collection for one approved mapping (Celery Beat dispatcher, P2-05)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    mapping = models.OneToOneField("customers.CustomerSourceMapping", on_delete=models.PROTECT, related_name="schedule")
    interval_hours = models.PositiveSmallIntegerField(
        default=24, validators=[MinValueValidator(1), MaxValueValidator(168)]
    )
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField()
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["enabled", "next_run_at"], name="integrations_sync_sched_due")]

    def __str__(self) -> str:
        return f"sync {self.mapping_id} every {self.interval_hours}h"
