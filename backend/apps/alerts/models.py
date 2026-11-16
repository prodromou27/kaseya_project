"""Per-user watchlists and in-portal alerts (OPS-04). Portal-owned; nothing is sent to or changed in VSA X."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class AlertSubscription(models.Model):
    class Kind(models.TextChoices):
        NEW_DEVICE = "new_device", "New device appears"
        OFFLINE = "offline", "Device not seen for more than N days"
        DISK_CRITICAL = "disk_critical", "System disk becomes critical"
        FORBIDDEN_SOFTWARE = "forbidden_software", "Program appears on a device"
        COMPLIANCE_BELOW = "compliance_below", "Compliance score falls below a threshold"
        WORKFLOW_FAILED = "workflow_failed", "An automation workflow fails on a device"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alert_subscriptions")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    params = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    # Keys currently matching (e.g. asset IDs); only keys that newly match raise an alert. None = not primed yet.
    state = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.customer_id}:{self.kind}"


class Alert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alerts")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="+")
    subscription = models.ForeignKey(AlertSubscription, null=True, on_delete=models.SET_NULL, related_name="alerts")
    kind = models.CharField(max_length=32)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True, help_text="Portal path, e.g. /device-health?disk=critical")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"], name="alerts_user_read_idx")]

    def __str__(self) -> str:
        return self.title
