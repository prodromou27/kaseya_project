"""Which devices need their per-device details fetched again (product owner, 2026-11-23: "only when needed").

Each sync still reads the whole device list (100 devices per call). The per-device detail calls (installed updates,
applied patch policies, notifications, custom fields) are made only for devices that are *due*:

* never collected, or
* an operator asked for a refresh after the last collection ("Refresh details now"), or
* the last collection is older than the kind's refresh interval AND the device was seen online since then, or
* the last collection is older than ``DETAIL_REFRESH_MAX_HOURS`` (ceiling, so a device whose ``LastSeenOnline`` does
  not move - e.g. if VSA X reports when it came online rather than when it was last seen - is never starved).

Devices that are not due keep their last collected values (carried forward by the existing carry-forward step).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import F, Q, QuerySet
from django.utils import timezone

REFRESH_SETTING = {
    "installed_updates": "DETAIL_REFRESH_HOURS_INSTALLED_UPDATES",
    "notifications": "DETAIL_REFRESH_HOURS_NOTIFICATIONS",
    "applied_policies": "DETAIL_REFRESH_HOURS_APPLIED_POLICIES",
    "custom_fields": "DETAIL_REFRESH_HOURS_CUSTOM_FIELDS",
}


def refresh_hours(kind: str) -> int:
    return int(getattr(settings, REFRESH_SETTING[kind]))


def only_due(qs: QuerySet[Any], kind: str) -> QuerySet[Any]:
    """``qs`` rows must have ``observation`` and ``asset`` relations and be annotated with ``last`` (latest
    successful collection in an earlier sync, NULL if never)."""
    now = timezone.now()
    interval_cutoff = now - timedelta(hours=refresh_hours(kind))
    ceiling_cutoff = now - timedelta(hours=int(settings.DETAIL_REFRESH_MAX_HOURS))
    seen_since = Q(observation__last_seen_online__isnull=True) | Q(observation__last_seen_online__gt=F("last"))
    return qs.filter(
        Q(last__isnull=True)
        | Q(asset__details_refresh_requested_at__gt=F("last"))
        | (Q(last__lt=interval_cutoff) & seen_since)
        | Q(last__lt=ceiling_cutoff)
    )
