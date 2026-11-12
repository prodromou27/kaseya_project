from __future__ import annotations

import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.accounts import roles


class Customer(models.Model):
    class Status(models.TextChoices):
        ONBOARDING = "onboarding", "Onboarding"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        ARCHIVED = "archived", "Archived"

    # Statuses in which customer members (non-super-admins) can see the customer.
    MEMBER_VISIBLE_STATUSES = (Status.ONBOARDING, Status.ACTIVE)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        max_length=32,
        unique=True,
        validators=[RegexValidator(r"^[A-Z0-9][A-Z0-9_-]{1,31}$", "Use 2-32 upper-case letters, digits, - or _.")],
    )
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ONBOARDING)
    data_region = models.CharField(max_length=64, blank=True, help_text="Approved data residency region.")
    restricted_data = models.BooleanField(
        default=False,
        help_text="Restricted/government data: ingestion requires a separately approved deployment (SECURITY.md §6).",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class CustomerMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    role = models.ForeignKey(
        "accounts.Role", on_delete=models.PROTECT, related_name="memberships", limit_choices_to={"is_global": False}
    )
    can_export = models.BooleanField(default=False, help_text="Grants export to a viewer membership.")
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["customer__name", "user__email"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "user"], name="customers_membership_customer_user_unique"),
        ]
        indexes = [models.Index(fields=["user", "is_active"], name="customers_m_user_active_idx")]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.customer_id}:{self.role_id}"

    @property
    def capabilities(self) -> frozenset[str]:
        caps = set(roles.capabilities_for_role(self.role.key))
        if self.can_export:
            caps.add(roles.Cap.CUSTOMER_EXPORT)
        return frozenset(caps)


class CustomerSourceMapping(models.Model):
    """Maps one vendor organisation (per integration instance) to exactly one approved customer.

    Only ``approved`` mappings may ever route source data to a customer. Unmapped/proposed/rejected
    source organisations are quarantined by collectors (P1-03).
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed (not trusted)"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        REVOKED = "revoked", "Revoked"

    LIVE_STATUSES = (Status.PROPOSED, Status.APPROVED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="source_mappings")
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.PROTECT, related_name="customer_mappings"
    )
    external_org_id = models.CharField(max_length=128, help_text="Vendor organisation ID (stored as text).")
    external_org_name = models.CharField(
        max_length=255, blank=True, help_text="Informational only; never used as an identity key."
    )
    mapping_status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One live (proposed or approved) mapping per source organisation: a source org can never map to
            # two customers at once.
            models.UniqueConstraint(
                fields=["integration_instance", "external_org_id"],
                condition=Q(mapping_status__in=["proposed", "approved"]),
                name="customers_mapping_one_live_per_source_org",
            ),
            models.CheckConstraint(
                condition=~Q(mapping_status="approved") | (Q(reviewed_by__isnull=False) & Q(reviewed_at__isnull=False)),
                name="customers_mapping_approved_requires_review",
            ),
            models.CheckConstraint(condition=~Q(external_org_id=""), name="customers_mapping_external_id_not_blank"),
        ]
        indexes = [models.Index(fields=["customer", "mapping_status"], name="customers_map_cust_status_idx")]

    def __str__(self) -> str:
        return f"{self.integration_instance_id}:{self.external_org_id} -> {self.customer_id} ({self.mapping_status})"
