"""Persist OS update sections for a staged generation (called by the sync engine)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from django.db import transaction
from django.db.models import F, Max, OuterRef, Q, Subquery
from django.utils import timezone

from apps.integrations.vsa.schema import OsUpdateItem, VsaAsset

from .models import DeviceOsUpdate, OsUpdate, PatchObservation, UpdateStatus

logger = logging.getLogger("portal.patching")


def _is_windows(device_type: str) -> bool:
    return device_type.strip().lower() == "windows"


def _list_status(section_present: bool, device_type: str) -> str:
    if section_present:
        return UpdateStatus.COLLECTED
    return UpdateStatus.NOT_COLLECTED if _is_windows(device_type) else UpdateStatus.NOT_SUPPORTED


def _os_updates(items: list[OsUpdateItem]) -> dict[tuple[str, Any], OsUpdate]:
    """PERF-03: resolve every update of one device in two or three queries (was one get_or_create per update).

    Creates the missing ones; fills a missing KB number, never overwrites with a blank."""
    wanted: dict[tuple[str, Any], OsUpdateItem] = {}
    for item in items:
        wanted.setdefault((item.update_id, item.revision_number), item)
    if not wanted:
        return {}

    def lookup() -> dict[tuple[str, Any], OsUpdate]:
        cond = Q()
        for uid, rev in wanted:
            cond |= Q(update_id=uid, revision_number=rev)
        return {(o.update_id, o.revision_number): o for o in OsUpdate.objects.filter(cond)}

    found = lookup()
    missing = [k for k in wanted if k not in found]
    if missing:
        OsUpdate.objects.bulk_create(
            [
                OsUpdate(
                    update_id=uid,
                    revision_number=rev,
                    kb_article=wanted[(uid, rev)].kb_article,
                    title=wanted[(uid, rev)].title,
                    severity=wanted[(uid, rev)].severity,
                    category=wanted[(uid, rev)].category,
                    release_date=wanted[(uid, rev)].release_date,
                )
                for uid, rev in missing
            ],
            ignore_conflicts=True,  # another sync may create the same update concurrently
        )
        found = lookup()
    gaps = [o for k, o in found.items() if not o.kb_article and wanted[k].kb_article]
    for o in gaps:
        o.kb_article = wanted[(o.update_id, o.revision_number)].kb_article
    if gaps:
        OsUpdate.objects.bulk_update(gaps, ["kb_article"])
    return found


def _write_rows(po: PatchObservation, items: Iterable[OsUpdateItem], state: str) -> int:
    items = list(items)
    updates = _os_updates(items)
    rows, seen = [], set()
    for item in items:
        upd = updates[(item.update_id, item.revision_number)]
        if upd.id in seen:
            continue
        seen.add(upd.id)
        rows.append(
            DeviceOsUpdate(
                customer_id=po.customer_id,
                asset_id=po.asset_id,
                patch_observation=po,
                generation_id=po.generation_id,
                os_update=upd,
                state=state,
                severity=item.severity,
                category=item.category,
                cvss_score=item.cvss_score,
                cve_codes=list(item.cve_codes),
                installed_at_raw=item.installed_at_raw,
                installed_by_agent=item.installed_by_agent,
            )
        )
    DeviceOsUpdate.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def record_list_sections(observation: Any, asset: VsaAsset) -> PatchObservation:
    status = _list_status(asset.available_updates is not None, asset.device_type)
    po = PatchObservation.objects.create(
        observation=observation,
        customer_id=observation.customer_id,
        asset_id=observation.asset_id,
        generation_id=observation.generation_id,
        update_counts=asset.update_counts,
        available_status=status,
        installed_status=(UpdateStatus.NOT_REQUESTED if _is_windows(asset.device_type) else UpdateStatus.NOT_SUPPORTED),
        collected_at=observation.collected_at,
    )
    if asset.available_updates is not None:
        po.available_count = _write_rows(po, asset.available_updates, DeviceOsUpdate.State.AVAILABLE)
        po.save(update_fields=["available_count"])
    return po


def pending_installed(generation: Any, limit: int) -> list[PatchObservation]:
    """Windows devices of this generation that are due (``freshness.only_due``), least-recently-collected first."""
    from apps.integrations.freshness import only_due

    if limit <= 0:
        return []
    last_collected = (
        PatchObservation.objects.filter(asset_id=OuterRef("asset_id"), installed_status=UpdateStatus.COLLECTED)
        .exclude(generation_id=generation.id)
        .values("asset_id")
        .annotate(m=Max("installed_collected_at"))
        .values("m")
    )
    qs = (
        PatchObservation.objects.filter(generation=generation, installed_status=UpdateStatus.NOT_REQUESTED)
        .filter(Q(observation__device_type__iexact="windows"))
        .annotate(last=Subquery(last_collected))
    )
    return list(
        only_due(qs, "installed_updates")
        .select_related("asset")
        # Never-collected devices first (PostgreSQL would otherwise sort NULLs last), then least recently collected.
        .order_by(F("last").asc(nulls_first=True), "asset__external_id")[:limit]
    )


def record_installed(po: PatchObservation, items: tuple[OsUpdateItem, ...] | None) -> None:
    with transaction.atomic():
        if items is None:
            po.installed_status = UpdateStatus.NOT_COLLECTED
            po.save(update_fields=["installed_status"])
            return
        po.installed_count = _write_rows(po, items, DeviceOsUpdate.State.INSTALLED)
        po.installed_status = UpdateStatus.COLLECTED
        po.installed_collected_at = timezone.now()
        po.save(update_fields=["installed_status", "installed_count", "installed_collected_at"])


def record_installed_failure(po: PatchObservation) -> None:
    PatchObservation.objects.filter(pk=po.pk).update(installed_status=UpdateStatus.FAILED)


def carry_forward(generation: Any) -> int:
    """For devices not fetched this run, copy installed updates from their latest successful collection.

    PERF-03: done in bulk (a handful of queries per sync instead of about four per device)."""
    waiting = {
        po.asset_id: po
        for po in PatchObservation.objects.filter(generation=generation, installed_status=UpdateStatus.NOT_REQUESTED)
    }
    if not waiting:
        return 0
    previous = {
        p.asset_id: p
        for p in PatchObservation.objects.filter(asset_id__in=list(waiting), installed_status=UpdateStatus.COLLECTED)
        .exclude(generation_id=generation.id)
        .order_by("asset_id", "-installed_collected_at", "-pk")
        .distinct("asset_id")
    }
    if not previous:
        return 0
    target = {p.pk: waiting[a] for a, p in previous.items()}
    counts: dict[Any, int] = {}
    rows = []
    for r in DeviceOsUpdate.objects.filter(
        patch_observation_id__in=list(target), state=DeviceOsUpdate.State.INSTALLED
    ).iterator(chunk_size=5000):
        po = target[r.patch_observation_id]
        counts[po.pk] = counts.get(po.pk, 0) + 1
        rows.append(
            DeviceOsUpdate(
                customer_id=po.customer_id,
                asset_id=po.asset_id,
                patch_observation=po,
                generation_id=po.generation_id,
                os_update_id=r.os_update_id,
                state=r.state,
                severity=r.severity,
                category=r.category,
                cvss_score=r.cvss_score,
                cve_codes=r.cve_codes,
                installed_at_raw=r.installed_at_raw,
                installed_by_agent=r.installed_by_agent,
            )
        )
    with transaction.atomic():
        DeviceOsUpdate.objects.bulk_create(rows, ignore_conflicts=True, batch_size=2000)
        changed = []
        for asset_id, prev in previous.items():
            po = waiting[asset_id]
            po.installed_status = UpdateStatus.CARRIED_FORWARD
            po.installed_count = counts.get(po.pk, 0)
            po.installed_collected_at = prev.installed_collected_at
            changed.append(po)
        PatchObservation.objects.bulk_update(
            changed, ["installed_status", "installed_count", "installed_collected_at"], batch_size=1000
        )
    return len(changed)
