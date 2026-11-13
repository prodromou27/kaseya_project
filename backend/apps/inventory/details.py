"""VSA4-03 budgeted per-device detail collection: notifications (PII-minimised) and allowlisted custom fields.

* Notifications: the ``NOTIFICATIONS_PER_DEVICE`` most recent per device; rows older than ``NOTIFICATION_WINDOW_DAYS``
  are dropped (counted, not stored). Message text is secret- and PII-redacted *before* storage.
* Custom fields: fetched only for customers with approved names (nothing is requested otherwise). Values of names
  that are not approved are never stored - only counted. Credential-like names can never be approved.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max, OuterRef, Subquery
from django.utils import timezone

from apps.core.redaction import SENSITIVE_KEY_RE, redact_text
from apps.integrations.vsa.schema import CustomFieldItem, NotificationItem

from .models import AssetObservation, CustomFieldAllowlist, DeviceCustomField, DeviceDetailFetch, DeviceNotification

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_ACCOUNT = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9._-]{0,30}\\[A-Za-z0-9._$-]{1,64}\b")  # DOMAIN\user
# Credential-like custom field names can never be allowlisted (in addition to the shared secret-key pattern).
_EXTRA_SENSITIVE = re.compile(r"(?i)(\bpin\b|\bkey\b|license.?key|recovery|bitlocker|passphrase|\bssn\b|\biban\b)")


def is_sensitive_field_name(name: str) -> bool:
    return bool(SENSITIVE_KEY_RE.search(name) or _EXTRA_SENSITIVE.search(name))


def minimise_message(text: str) -> tuple[str, int]:
    """Remove secrets, e-mail addresses and DOMAIN\\user accounts. Returns (text, number of replacements)."""
    redacted = redact_text(text)
    count = int(redacted != text)
    redacted, n_email = _EMAIL.subn("[email]", redacted)
    redacted, n_account = _ACCOUNT.subn("[account]", redacted)
    return redacted, count + n_email + n_account


def approved_field_keys(customer_id: Any) -> set[str]:
    return set(
        CustomFieldAllowlist.objects.filter(
            customer_id=customer_id, state=CustomFieldAllowlist.State.APPROVED
        ).values_list("name_key", flat=True)
    )


def ensure_fetches(generation: Any, kind: str) -> None:
    existing = set(
        DeviceDetailFetch.objects.filter(generation=generation, kind=kind).values_list("observation_id", flat=True)
    )
    DeviceDetailFetch.objects.bulk_create(
        [
            DeviceDetailFetch(
                observation_id=o.pk,
                customer_id=o.customer_id,
                asset_id=o.asset_id,
                generation_id=generation.pk,
                kind=kind,
            )
            for o in AssetObservation.objects.filter(generation=generation).only("pk", "customer_id", "asset_id")
            if o.pk not in existing
        ],
        batch_size=1000,
    )


def pending(generation: Any, kind: str, limit: int) -> list[DeviceDetailFetch]:
    """Never-collected devices first, then least recently collected (rotation across syncs)."""
    if limit <= 0:
        return []
    last = (
        DeviceDetailFetch.objects.filter(
            asset_id=OuterRef("asset_id"), kind=kind, status=DeviceDetailFetch.Status.COLLECTED
        )
        .exclude(generation_id=generation.id)
        .values("asset_id")
        .annotate(m=Max("collected_at"))
        .values("m")
    )
    return list(
        DeviceDetailFetch.objects.filter(
            generation=generation, kind=kind, status=DeviceDetailFetch.Status.NOT_REQUESTED
        )
        .annotate(last=Subquery(last))
        .select_related("asset")
        .order_by(F("last").asc(nulls_first=True), "asset__external_id")[:limit]
    )


def record_notifications(fetch: DeviceDetailFetch, items: Iterable[NotificationItem]) -> None:
    items = list(items)
    cutoff = timezone.now() - timedelta(days=settings.NOTIFICATION_WINDOW_DAYS)
    keep = [i for i in items if i.occurred_at is None or i.occurred_at >= cutoff]
    rows = []
    for i in keep:
        text, n = minimise_message(i.message)
        rows.append(
            DeviceNotification(
                fetch=fetch,
                customer_id=fetch.customer_id,
                asset_id=fetch.asset_id,
                generation_id=fetch.generation_id,
                vendor_id=i.vendor_id[:32],
                priority=i.priority,
                occurred_at=i.occurred_at,
                occurred_raw=i.occurred_raw,
                message=text[:1000],
                redactions=min(n, 32767),
            )
        )
    with transaction.atomic():
        DeviceNotification.objects.bulk_create(rows)
        _done(fetch, reported=len(items), stored=len(rows), dropped=len(items) - len(rows))


def record_custom_fields(fetch: DeviceDetailFetch, items: Iterable[CustomFieldItem], approved: set[str]) -> None:
    items = list(items)
    keep = [i for i in items if i.name.casefold() in approved and not is_sensitive_field_name(i.name)]
    with transaction.atomic():
        DeviceCustomField.objects.bulk_create(
            [
                DeviceCustomField(
                    fetch=fetch,
                    customer_id=fetch.customer_id,
                    asset_id=fetch.asset_id,
                    generation_id=fetch.generation_id,
                    field_id=i.field_id[:32],
                    name=i.name,
                    value=i.value,
                    type=i.type,
                )
                for i in keep
            ]
        )
        _done(fetch, reported=len(items), stored=len(keep), dropped=len(items) - len(keep))


def _done(fetch: DeviceDetailFetch, *, reported: int, stored: int, dropped: int) -> None:
    fetch.status, fetch.collected_at = DeviceDetailFetch.Status.COLLECTED, timezone.now()
    fetch.reported, fetch.stored, fetch.dropped = reported, stored, dropped
    fetch.save(update_fields=["status", "collected_at", "reported", "stored", "dropped"])


def record_failure(fetch: DeviceDetailFetch) -> None:
    DeviceDetailFetch.objects.filter(pk=fetch.pk).update(status=DeviceDetailFetch.Status.FAILED)


# ---------------------------------------------------------------------------------------------- read model


def _pattern(message: str) -> str:
    """Group recurring notifications: digits, quoted names and sizes collapse to placeholders."""
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", message)
    text = re.sub(r"\d+([.,]\d+)?", "#", text)
    return text[:160]


def summary(customer_id: Any) -> dict[str, Any]:
    from collections import Counter

    from .queries import current_generations

    gens = list(current_generations(customer_id))
    fetches = DeviceDetailFetch.objects.filter(customer_id=customer_id, generation__in=gens, kind="notifications")
    status = Counter(fetches.values_list("status", flat=True))
    notes = DeviceNotification.objects.filter(customer_id=customer_id, generation__in=gens)
    priorities = Counter(notes.values_list("priority", flat=True))
    patterns: Counter[str] = Counter()
    devices_per_pattern: dict[str, set[Any]] = {}
    for message, asset_id in notes.values_list("message", "asset_id"):
        p = _pattern(message)
        patterns[p] += 1
        devices_per_pattern.setdefault(p, set()).add(asset_id)
    devices_total = AssetObservation.objects.filter(customer_id=customer_id, generation__in=gens).count()
    return {
        "as_of": [g.published_at.isoformat() if g.published_at else None for g in gens],
        "window_days": settings.NOTIFICATION_WINDOW_DAYS,
        "per_device_limit": settings.NOTIFICATIONS_PER_DEVICE,
        "devices": devices_total,
        "collection_status": {s.value: status.get(s.value, 0) for s in DeviceDetailFetch.Status},
        "devices_without_fetch_row": devices_total - sum(status.values()),
        "notifications": notes.count(),
        "devices_with_notifications": notes.values("asset_id").distinct().count(),
        "by_priority": dict(sorted(priorities.items())),
        "recurring": [
            {"pattern": p, "count": n, "devices": len(devices_per_pattern[p])}
            for p, n in patterns.most_common(20)
            if n > 1
        ],
        "note": "Device notifications from VSA X within the retention window. Message text is redacted for "
        "credentials, e-mail addresses and DOMAIN\\user accounts before storage. Devices not collected are not "
        "'without notifications'.",
    }
