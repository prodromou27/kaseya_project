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


def _os_update(item: OsUpdateItem) -> OsUpdate:
    obj, created = OsUpdate.objects.get_or_create(
        update_id=item.update_id,
        revision_number=item.revision_number,
        defaults={
            "kb_article": item.kb_article,
            "title": item.title,
            "severity": item.severity,
            "category": item.category,
            "release_date": item.release_date,
        },
    )
    if not created and item.kb_article and not obj.kb_article:  # fill gaps, never overwrite with blanks
        obj.kb_article = item.kb_article
        obj.save(update_fields=["kb_article"])
    return obj


def _write_rows(po: PatchObservation, items: Iterable[OsUpdateItem], state: str) -> int:
    rows, seen = [], set()
    for item in items:
        upd = _os_update(item)
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
    """Windows devices of this generation not yet fetched, least-recently-collected first (rotation)."""
    if limit <= 0:
        return []
    last_collected = (
        PatchObservation.objects.filter(asset_id=OuterRef("asset_id"), installed_status=UpdateStatus.COLLECTED)
        .exclude(generation_id=generation.id)
        .values("asset_id")
        .annotate(m=Max("installed_collected_at"))
        .values("m")
    )
    return list(
        PatchObservation.objects.filter(generation=generation, installed_status=UpdateStatus.NOT_REQUESTED)
        .filter(Q(observation__device_type__iexact="windows"))
        .annotate(last=Subquery(last_collected))
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
    """For devices not fetched this run, copy installed updates from their latest successful collection."""
    carried = 0
    for po in PatchObservation.objects.filter(generation=generation, installed_status=UpdateStatus.NOT_REQUESTED):
        previous = (
            PatchObservation.objects.filter(asset_id=po.asset_id, installed_status=UpdateStatus.COLLECTED)
            .exclude(generation_id=generation.id)
            .order_by("-installed_collected_at")
            .first()
        )
        if previous is None:
            continue
        with transaction.atomic():
            rows = [
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
                for r in previous.updates.filter(state=DeviceOsUpdate.State.INSTALLED)
            ]
            DeviceOsUpdate.objects.bulk_create(rows, ignore_conflicts=True)
            po.installed_status = UpdateStatus.CARRIED_FORWARD
            po.installed_count = len(rows)
            po.installed_collected_at = previous.installed_collected_at
            po.save(update_fields=["installed_status", "installed_count", "installed_collected_at"])
        carried += 1
    return carried
