"""Customer-keyed OS update read models (RPT-04 basis). Definitions follow docs/REPORTING.md §2:
counts are based on actual ``AvailableUpdates`` records; devices whose section was absent or unsupported are
reported separately and are never counted as "0 missing updates"."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import Count, Q, QuerySet

from apps.inventory.queries import current_generations

from .models import DeviceOsUpdate, PatchObservation, UpdateStatus

FRESHNESS_NOTE = (
    "The VSA X API does not document a per-device update-scan timestamp. Freshness shown is the portal collection "
    "time and the device's LastSeenOnline."
)
SEVERITIES = ["Critical", "Important", "Moderate", "Low", "Unspecified"]


def current_patch_observations(customer_id: Any) -> QuerySet[PatchObservation]:
    return PatchObservation.objects.filter(customer_id=customer_id, generation__in=current_generations(customer_id))


def current_device_updates(customer_id: Any) -> QuerySet[DeviceOsUpdate]:
    return DeviceOsUpdate.objects.filter(
        customer_id=customer_id, generation__in=current_generations(customer_id)
    ).select_related("os_update", "patch_observation__observation")


def summary(customer_id: Any) -> dict[str, Any]:
    pos = current_patch_observations(customer_id)
    by_available = {s: 0 for s in UpdateStatus.values}
    for row in pos.values("available_status").annotate(n=Count("id")):
        by_available[row["available_status"]] = row["n"]
    by_installed = {s: 0 for s in UpdateStatus.values}
    for row in pos.values("installed_status").annotate(n=Count("id")):
        by_installed[row["installed_status"]] = row["n"]
    collected = pos.filter(available_status=UpdateStatus.COLLECTED)
    available_rows = current_device_updates(customer_id).filter(state=DeviceOsUpdate.State.AVAILABLE)
    devices_any = available_rows.values("asset_id").distinct().count()
    by_severity = {
        sev: available_rows.filter(severity__iexact=sev).values("asset_id").distinct().count() for sev in SEVERITIES
    }
    other_severity = (
        available_rows.exclude(
            Q(severity__iexact="Critical")
            | Q(severity__iexact="Important")
            | Q(severity__iexact="Moderate")
            | Q(severity__iexact="Low")
            | Q(severity__iexact="Unspecified")
        )
        .values("asset_id")
        .distinct()
        .count()
    )
    top = list(
        available_rows.values("os_update_id", "os_update__kb_article", "os_update__title", "os_update__severity")
        .annotate(devices=Count("asset_id", distinct=True))
        .order_by("-devices", "os_update__kb_article")[:50]
    )
    gens = list(current_generations(customer_id))
    return {
        "as_of": [g.published_at for g in gens],
        "generation_ids": [str(g.id) for g in gens],
        "data_basis": sorted({g.data_basis for g in gens}),
        "devices_total": pos.count(),
        "available_section": by_available,
        "devices_reporting_updates": collected.count(),
        "devices_with_available_updates": devices_any,
        "devices_with_zero_available": collected.filter(available_count=0).count(),
        "devices_by_severity": by_severity,
        "devices_with_other_severity": other_severity,
        "installed_section": by_installed,
        "top_available_updates": [
            {
                "os_update_id": str(r["os_update_id"]),
                "kb_article": r["os_update__kb_article"],
                "title": r["os_update__title"],
                "severity": r["os_update__severity"],
                "devices": r["devices"],
            }
            for r in top
        ],
        "freshness_note": FRESHNESS_NOTE,
        "scope_note": "Operating-system updates reported by VSA X only. Not third-party application patches.",
    }


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def filtered_device_updates(customer_id: Any, params: Any) -> QuerySet[DeviceOsUpdate]:
    qs = current_device_updates(customer_id)
    state = params.get("state")
    if state in DeviceOsUpdate.State.values:
        qs = qs.filter(state=state)
    severity = (params.get("severity") or "").strip()[:32]
    if severity:
        qs = qs.filter(severity__iexact=severity)
    kb = (params.get("kb") or "").strip().upper().removeprefix("KB")[:10]
    if kb:
        qs = qs.filter(os_update__kb_article=kb) if kb.isdigit() else qs.none()
    for param, field in (("asset", "asset_id"), ("os_update", "os_update_id")):
        value = (params.get(param) or "").strip()
        if value:
            parsed = _uuid(value)
            qs = qs.filter(**{field: parsed}) if parsed else qs.none()
    return qs


def filtered_devices(customer_id: Any, params: Any) -> QuerySet[PatchObservation]:
    qs = current_patch_observations(customer_id).select_related("observation", "asset")
    for param, field in (("available_status", "available_status"), ("installed_status", "installed_status")):
        value = params.get(param)
        if value in UpdateStatus.values:
            qs = qs.filter(**{field: value})
    return qs
