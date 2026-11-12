"""Historical trends from retained published generations (P2-06, RPT-09).

One point per published (or superseded) generation, keeping the latest generation per UTC day and source.
Each point carries its own denominators and the exact generation / evaluation / catalog revision identities, so a
figure can always be traced back and reproduced. Nothing is interpolated: days without a published generation have
no point.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Count
from django.utils import timezone

from apps.integrations.models import DatasetGeneration
from apps.patching.models import DeviceOsUpdate, PatchObservation, UpdateStatus
from apps.software.models import ComplianceEvaluation, ComplianceResult

MAX_POINTS = 400


def trend_points(customer_id: Any, days: int) -> dict[str, Any]:
    since = timezone.now() - timedelta(days=days)
    gens = list(
        DatasetGeneration.objects.filter(
            customer_id=customer_id,
            dataset="vsa_assets",
            state__in=["published", "superseded"],
            published_at__gte=since,
            mapping__mapping_status="approved",
        )
        .select_related("integration_instance")
        .order_by("published_at")[: MAX_POINTS * 4]
    )
    latest_per_day: dict[tuple[str, Any], DatasetGeneration] = {}
    for g in gens:
        latest_per_day[(g.published_at.date().isoformat(), g.integration_instance_id)] = g
    points = []
    for (day, _), g in sorted(latest_per_day.items(), key=lambda kv: kv[1].published_at)[-MAX_POINTS:]:
        evaluation = ComplianceEvaluation.objects.filter(generation=g, is_current=True).first()
        sw = evaluation.summary if evaluation else {}
        outdated_devices = (
            ComplianceResult.objects.filter(evaluation=evaluation, state="outdated")
            .values("asset_id")
            .distinct()
            .count()
            if evaluation
            else None
        )
        po = PatchObservation.objects.filter(generation=g)
        reporting = po.filter(available_status=UpdateStatus.COLLECTED).count()
        avail = DeviceOsUpdate.objects.filter(generation=g, state=DeviceOsUpdate.State.AVAILABLE)
        points.append(
            {
                "day": day,
                "as_of": g.published_at,
                "source": g.integration_instance.name,
                "generation_id": str(g.id),
                "data_basis": g.data_basis,
                "devices": g.row_count,
                "software": None
                if evaluation is None
                else {
                    "evaluation_id": str(evaluation.id),
                    "catalog_revision_ids": evaluation.revision_ids,
                    "algorithm_version": evaluation.algorithm_version,
                    "current": sw.get("current", 0),
                    "outdated": sw.get("outdated", 0),
                    "comparable": sw.get("current", 0) + sw.get("outdated", 0) + sw.get("newer", 0),
                    "eligible": sum(sw.values()),
                    "devices_with_outdated": outdated_devices,
                },
                "os_updates": {
                    "devices_reporting": reporting,
                    "devices_not_reporting": po.exclude(available_status=UpdateStatus.COLLECTED).count(),
                    "devices_with_available": avail.values("asset_id").distinct().count(),
                    "devices_with_critical": avail.filter(severity__iexact="critical")
                    .values("asset_id")
                    .distinct()
                    .count(),
                },
            }
        )
    by_status = dict(
        DatasetGeneration.objects.filter(customer_id=customer_id, dataset="vsa_assets")
        .values_list("state")
        .annotate(n=Count("id"))
    )
    return {
        "days": days,
        "points": points,
        "generations_by_state": by_status,
        "method": "Latest published generation per UTC day and source; no interpolation. Denominators per point.",
    }
