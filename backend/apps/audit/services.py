from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from apps.core.redaction import redact
from apps.core.request_context import get_request_id

from .models import AuditEvent

logger = logging.getLogger("portal.audit")


def _client_ip(request: Any) -> str | None:
    if request is None:
        return None
    # REMOTE_ADDR is set by the trusted reverse proxy hop; X-Forwarded-For is not trusted here.
    meta = getattr(request, "META", None) or getattr(getattr(request, "_request", None), "META", {})
    ip = meta.get("REMOTE_ADDR") if meta else None
    return ip or None


def record_event(
    *,
    action: str,
    outcome: str,
    actor: Any = None,
    customer: Any = None,
    target_type: str = "",
    target_id: str = "",
    request: Any = None,
    metadata: dict[str, Any] | None = None,
    actor_label: str = "",
) -> AuditEvent:
    """Append an audit event. Metadata is redacted; never pass secrets or full personal-data objects."""
    actor_obj = actor if getattr(actor, "is_authenticated", False) else None
    label = actor_label or (actor_obj.email if actor_obj is not None else "")
    customer_id = getattr(customer, "pk", customer)
    event = AuditEvent.objects.create(
        actor=actor_obj,
        actor_label=label[:254],
        action=action[:64],
        customer_id=customer_id,
        target_type=target_type[:64],
        target_id=str(target_id)[:200],
        outcome=outcome,
        request_id=(get_request_id() or "")[:64],
        source_ip=_client_ip(request) if getattr(settings, "AUDIT_RECORD_SOURCE_IP", True) else None,
        metadata=redact(metadata or {}),
    )
    logger.info(
        "audit_event",
        extra={
            "audit_action": event.action,
            "audit_outcome": event.outcome,
            "audit_id": str(event.id),
            "customer_id": str(customer_id) if customer_id else None,
            "target_type": event.target_type,
            "target_id": event.target_id,
        },
    )
    return event
