"""Compliance baselines: customer-defined rules evaluated against the current published inventory.

A baseline is portal-owned configuration (nothing is written to VSA X). Results are computed from the current
snapshot on read, so they always match the data on screen; every rule answers pass / fail / unknown, and unknown
(data not collected) is never counted as a pass or a failure.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class ComplianceBaseline(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="compliance_baselines")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=True)
    # Optional scope; blank = every device of the customer.
    scope_device_type = models.CharField(max_length=64, blank=True, help_text="e.g. windows; blank = all types")
    scope_site_external_id = models.CharField(max_length=64, blank=True)
    scope_group_external_id = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["customer", "name"], name="compliance_baseline_name_unique")]

    def __str__(self) -> str:
        return f"{self.customer_id}:{self.name}"


class BaselineRule(models.Model):
    class Kind(models.TextChoices):
        REQUIRED_SOFTWARE = "required_software", "Required software is installed"
        FORBIDDEN_SOFTWARE = "forbidden_software", "Forbidden software is not installed"
        OS_MIN_VERSION = "os_min_version", "Operating system version at least"
        ANTIVIRUS_HEALTHY = "antivirus_healthy", "Antivirus enabled and up to date"
        FIREWALL_ENABLED = "firewall_enabled", "Firewall enabled"
        DISK_FREE_MIN = "disk_free_min", "System disk free space at least"
        MAX_DAYS_OFFLINE = "max_days_offline", "Seen within a number of days"
        AGENT_CURRENT = "agent_current", "Agent at or above the approved minimum"
        NO_OUTDATED_SOFTWARE = "no_outdated_software", "No outdated catalogued software"
        NO_CRITICAL_UPDATES = "no_critical_updates", "No available Critical OS updates"
        PATCH_POLICY_ASSIGNED = "patch_policy_assigned", "A patch policy is assigned"
        SCRIPT_VALUE = "script_value", "A value collected by a VSA script matches"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    baseline = models.ForeignKey(ComplianceBaseline, on_delete=models.CASCADE, related_name="rules")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    params = models.JSONField(default=dict, blank=True)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.MEDIUM)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.baseline_id}:{self.kind}"
