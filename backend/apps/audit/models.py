from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class AppendOnlyError(RuntimeError):
    pass


class AuditEventQuerySet(models.QuerySet["AuditEvent"]):
    def update(self, **kwargs: object) -> int:
        raise AppendOnlyError("Audit events are append-only.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise AppendOnlyError("Audit events are append-only.")


class AuditEvent(models.Model):
    """Append-only audit record.

    Enforced at three layers: this model (save/delete), the queryset (update/delete), and a PostgreSQL
    trigger that rejects UPDATE/DELETE on the table (migration 0002). Local DB audit is not tamper-proof
    on its own; forward to central logging per SECURITY.md §5 (P5-05).
    """

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        DENIED = "denied", "Denied"
        FAILURE = "failure", "Failure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_label = models.CharField(max_length=254, blank=True, help_text="Actor email/system name at event time.")
    action = models.CharField(max_length=64)
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="audit_events"
    )
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=200, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    request_id = models.CharField(max_length=64, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "-created_at"], name="audit_customer_created_idx"),
            models.Index(fields=["action", "-created_at"], name="audit_action_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%dT%H:%M:%S} {self.action} {self.outcome}"

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Audit events are append-only.")
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise AppendOnlyError("Audit events are append-only.")
