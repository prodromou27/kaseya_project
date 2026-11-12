from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class SoftwareInstallation(models.Model):
    """One ``InstalledSoftware`` entry observed on an asset in a generation. Raw values are never altered."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey("inventory.Asset", on_delete=models.PROTECT, related_name="software")
    observation = models.ForeignKey("inventory.AssetObservation", on_delete=models.PROTECT, related_name="software")
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="software_installations"
    )
    raw_name = models.CharField(max_length=255)
    raw_publisher = models.CharField(max_length=255, blank=True)
    raw_version = models.CharField(max_length=255, blank=True)
    row_hash = models.CharField(max_length=64, help_text="Distinguishes identical duplicate entries on one asset.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["asset", "generation", "row_hash"], name="software_install_unique")
        ]
        indexes = [
            models.Index(fields=["customer", "generation"], name="software_inst_cust_gen_idx"),
            models.Index(fields=["asset", "generation"], name="software_inst_asset_gen_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.raw_name} {self.raw_version}"


class SoftwareProduct(models.Model):
    """A catalogued product *line*. Channel/edition/architecture are part of identity (no cross-channel compares)."""

    class Architecture(models.TextChoices):
        ANY = "any", "Any / not architecture-specific"
        X64 = "x64", "x64"
        X86 = "x86", "x86"
        ARM64 = "arm64", "ARM64"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.CharField(max_length=120)
    product = models.CharField(max_length=160)
    edition = models.CharField(max_length=64, blank=True)
    platform = models.CharField(max_length=32, default="windows")
    channel = models.CharField(max_length=32, default="stable")
    architecture = models.CharField(max_length=8, choices=Architecture.choices, default=Architecture.ANY)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["vendor", "product", "channel"]
        constraints = [
            models.UniqueConstraint(
                fields=["vendor", "product", "edition", "platform", "channel", "architecture"],
                name="software_product_identity_unique",
            )
        ]

    def __str__(self) -> str:
        parts = [self.vendor, self.product, self.edition, self.channel, self.architecture]
        return " ".join(p for p in parts if p)


class ReviewStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class SoftwareAlias(models.Model):
    """How raw ``InstalledSoftware`` names map to a product. Unreviewed aliases never drive classification."""

    class MatchType(models.TextChoices):
        EXACT = "exact", "Exact (case-insensitive)"
        PREFIX = "prefix", "Prefix (case-insensitive)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(SoftwareProduct, on_delete=models.PROTECT, related_name="aliases")
    name_pattern = models.CharField(max_length=255)
    publisher_pattern = models.CharField(max_length=255, blank=True, help_text="Exact publisher; blank = any.")
    match_type = models.CharField(max_length=8, choices=MatchType.choices, default=MatchType.EXACT)
    review_status = models.CharField(max_length=10, choices=ReviewStatus.choices, default=ReviewStatus.PROPOSED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name_pattern"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(review_status="approved") | Q(reviewed_by__isnull=False),
                name="software_alias_approved_requires_reviewer",
            )
        ]

    def __str__(self) -> str:
        return f"{self.match_type}:{self.name_pattern} -> {self.product_id}"


class CatalogImport(models.Model):
    """A batch of proposed reference versions. Preview first; a reviewer approves to create published revisions."""

    class State(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    rows = models.JSONField()
    preview = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"import {self.id} ({self.state})"


class CatalogRevision(models.Model):
    """Reviewed reference version for a product. Immutable once published (model guard + DB trigger)."""

    class State(models.TextChoices):
        PUBLISHED = "published", "Published"
        RETIRED = "retired", "Retired"

    class Scheme(models.TextChoices):
        DOTTED_NUMERIC = "dotted_numeric", "Dotted numeric (e.g. 131.0.6778.86)"

    IMMUTABLE_FIELDS = (
        "product_id",
        "reference_version",
        "version_scheme",
        "vendor_url",
        "source_type",
        "source_checked_at",
        "effective_at",
        "reviewed_by_id",
        "reviewed_at",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(SoftwareProduct, on_delete=models.PROTECT, related_name="revisions")
    reference_version = models.CharField(max_length=64)
    version_scheme = models.CharField(max_length=24, choices=Scheme.choices, default=Scheme.DOTTED_NUMERIC)
    vendor_url = models.URLField(max_length=500, blank=True)
    source_type = models.CharField(max_length=32, help_text="e.g. vendor_release_notes, vendor_feed, manual")
    source_checked_at = models.DateTimeField()
    effective_at = models.DateTimeField()
    state = models.CharField(max_length=10, choices=State.choices, default=State.PUBLISHED)
    catalog_import = models.ForeignKey(
        CatalogImport, null=True, blank=True, on_delete=models.PROTECT, related_name="revisions"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_at"]
        indexes = [models.Index(fields=["product", "state", "-effective_at"], name="software_rev_prod_eff_idx")]

    def __str__(self) -> str:
        return f"{self.product_id} {self.reference_version} ({self.state})"

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            original = CatalogRevision.objects.get(pk=self.pk)
            changed = [f for f in self.IMMUTABLE_FIELDS if getattr(original, f) != getattr(self, f)]
            if changed:
                raise ValueError(f"Published catalog revisions are immutable (attempted: {', '.join(changed)}).")
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class SoftwareException(models.Model):
    """Approved exclusion. Never alters the observed installation; expiry is mandatory."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="software_exceptions")
    product = models.ForeignKey(SoftwareProduct, on_delete=models.PROTECT, related_name="exceptions")
    asset = models.ForeignKey("inventory.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-approved_at"]

    def __str__(self) -> str:
        return f"exception {self.product_id} for {self.customer_id}"


class ComplianceEvaluation(models.Model):
    """One classification pass over a generation's installations under a fixed catalog state."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="compliance_evaluations"
    )
    algorithm_version = models.CharField(max_length=16)
    catalog_fingerprint = models.CharField(max_length=64, help_text="Hash of approved aliases + revisions used.")
    revision_ids = models.JSONField(default=list)
    is_current = models.BooleanField(default=False)
    summary = models.JSONField(default=dict)
    evaluated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-evaluated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["generation"], condition=Q(is_current=True), name="software_one_current_eval_per_generation"
            )
        ]

    def __str__(self) -> str:
        return f"evaluation {self.id}"


class ComplianceResult(models.Model):
    class State(models.TextChoices):
        CURRENT = "current", "Current"
        OUTDATED = "outdated", "Outdated"
        NEWER = "newer", "Newer than reference"
        UNKNOWN = "unknown", "Unknown"
        UNSUPPORTED = "unsupported", "Unsupported (not catalogued)"
        EXCLUDED = "excluded", "Excluded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evaluation = models.ForeignKey(ComplianceEvaluation, on_delete=models.CASCADE, related_name="results")
    installation = models.ForeignKey(SoftwareInstallation, on_delete=models.PROTECT, related_name="results")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey("inventory.Asset", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey(SoftwareProduct, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    catalog_revision = models.ForeignKey(
        CatalogRevision, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    exception = models.ForeignKey(SoftwareException, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    state = models.CharField(max_length=12, choices=State.choices)
    reason_code = models.CharField(max_length=48)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["evaluation", "installation"], name="software_result_unique")]
        indexes = [
            models.Index(fields=["evaluation", "state", "product"], name="software_res_eval_state"),
            models.Index(fields=["evaluation", "asset"], name="software_res_eval_asset"),
        ]

    def __str__(self) -> str:
        return f"{self.installation_id}: {self.state} ({self.reason_code})"
