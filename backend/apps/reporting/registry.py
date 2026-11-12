"""Report type registry. Report types are code, never user-supplied templates or queries.

P0 ships one report type (customer audit log CSV) to prove the async job → private artifact → reauthorised
download path end to end. Inventory/software/OS-update reports are added in P1/P2.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from rest_framework import serializers

from apps.accounts.roles import Cap


@dataclass(frozen=True)
class ReportType:
    key: str
    title: str
    formats: tuple[str, ...]
    # Capabilities required on the report's customer to request, view *and* download it.
    required_capabilities: frozenset[str]
    filter_serializer: type[serializers.Serializer]
    columns: tuple[str, ...]
    rows: Callable[[Any, dict[str, Any]], Iterator[list[Any]]]
    data_basis: str = "portal_internal"
    extra: dict[str, Any] = field(default_factory=dict)


class AuditLogFilters(serializers.Serializer):
    action_prefix = serializers.CharField(required=False, allow_blank=True, max_length=64)
    outcome = serializers.ChoiceField(choices=["success", "denied", "failure"], required=False)
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)


def _audit_rows(customer: Any, filters: dict[str, Any]) -> Iterator[list[Any]]:
    from apps.audit.models import AuditEvent

    qs = AuditEvent.objects.filter(customer=customer).order_by("created_at", "id")
    if filters.get("action_prefix"):
        qs = qs.filter(action__startswith=filters["action_prefix"])
    if filters.get("outcome"):
        qs = qs.filter(outcome=filters["outcome"])
    if filters.get("since"):
        qs = qs.filter(created_at__gte=filters["since"])
    if filters.get("until"):
        qs = qs.filter(created_at__lt=filters["until"])
    for e in qs.iterator(chunk_size=2000):
        yield [
            e.created_at.isoformat(),
            e.action,
            e.outcome,
            e.actor_label,
            e.target_type,
            e.target_id,
            e.request_id,
        ]


REPORT_TYPES: dict[str, ReportType] = {
    "customer_audit_log": ReportType(
        key="customer_audit_log",
        title="Customer audit log",
        formats=("csv",),
        required_capabilities=frozenset({Cap.CUSTOMER_EXPORT, Cap.CUSTOMER_AUDIT_READ}),
        filter_serializer=AuditLogFilters,
        columns=("created_at_utc", "action", "outcome", "actor", "target_type", "target_id", "request_id"),
        rows=_audit_rows,
    ),
}
