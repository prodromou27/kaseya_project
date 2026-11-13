"""VSA2-01/03: upload storage, comparison gating against a pinned complete generation, worker, review, purge."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.integrations.models import DatasetGeneration
from apps.inventory.models import (
    AssetObservation,
    GroupNode,
    IpAddressObservation,
    NetworkAdapterObservation,
    OrganizationNode,
    SiteNode,
)
from apps.inventory.queries import current_generations

from . import importer, matching
from .models import ExpectedInventoryUpload, ReconciliationResult, ReconciliationRun

logger = logging.getLogger("portal.onboarding")


class Blocked(Exception):
    """Comparison refused before a run is created. ``code``/``message`` are safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------------------------- storage


def _storage_path(storage_key: str) -> Path:
    base = Path(settings.ONBOARDING_STORAGE_DIR).resolve()
    path = (base / storage_key).resolve()
    if path.parent != base:
        raise ValueError("Invalid storage key.")
    return path


def _display_name(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    return re.sub(r"[^\w .()\-]", "_", name)[:120] or "upload"


def store_upload(user: Any, customer: Any, filename: str, data: bytes, request: Any) -> ExpectedInventoryUpload:
    """Validate + parse first (rejects before anything is written), then persist privately with a TTL."""
    workbook = importer.parse(filename, data)
    storage_key = f"{uuid.uuid4().hex}.upload"
    path = _storage_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    upload = ExpectedInventoryUpload.objects.create(
        customer=customer,
        uploaded_by=user,
        display_name=_display_name(filename),
        file_format=workbook.file_format,
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        storage_key=storage_key,
        sheets=[
            {
                "name": s.name,
                "rows": len(s.rows),
                "columns": s.width,
                "formula_cells_ignored": s.formula_cells,
                "truncated_cells": s.truncated_cells,
            }
            for s in workbook.sheets
        ],
        expires_at=timezone.now() + timedelta(hours=settings.ONBOARDING_UPLOAD_TTL_HOURS),
    )
    record_event(
        action="onboarding.upload",
        outcome="success",
        actor=user,
        customer=customer,
        target_type="onboarding_upload",
        target_id=str(upload.id),
        request=request,
        metadata={"sha256": upload.sha256, "bytes": upload.bytes, "format": upload.file_format},
    )
    return upload


def load_workbook(upload: ExpectedInventoryUpload) -> importer.Workbook:
    if upload.purged_at or upload.expires_at <= timezone.now():
        raise importer.ImportRejected("upload_expired", "The uploaded file has expired; upload it again.")
    data = _storage_path(upload.storage_key).read_bytes()
    if hashlib.sha256(data).hexdigest() != upload.sha256:
        raise importer.ImportRejected("upload_integrity", "The stored upload failed its integrity check.")
    return importer.parse(f"upload.{upload.file_format}", data)


def purge_upload(
    upload: ExpectedInventoryUpload, *, actor: Any = None, actor_label: str = "", request: Any = None
) -> None:
    _storage_path(upload.storage_key).unlink(missing_ok=True)
    upload.purged_at = timezone.now()
    upload.save(update_fields=["purged_at"])
    record_event(
        action="onboarding.upload_purged",
        outcome="success",
        actor=actor,
        actor_label=actor_label,
        customer=upload.customer_id,
        target_type="onboarding_upload",
        target_id=str(upload.id),
        request=request,
        metadata={"sha256": upload.sha256},
    )


def purge_expired_uploads(now: Any = None) -> int:
    now = now or timezone.now()
    count = 0
    for upload in ExpectedInventoryUpload.objects.filter(expires_at__lte=now, purged_at__isnull=True):
        try:
            purge_upload(upload, actor_label="system:retention")
            count += 1
        except (OSError, ValueError):
            logger.exception("onboarding_purge_failed", extra={"upload_id": str(upload.id)})
    return count


# ---------------------------------------------------------------------------------------------- gating


def choose_generation(customer: Any, generation_id: Any, allow_stale: bool) -> tuple[DatasetGeneration, bool]:
    """Only the customer's *current, published* generation from an *approved* mapping is comparable.

    Another customer's generation ID is indistinguishable from an unknown one (no existence leak).
    """
    gens = list(current_generations(customer.pk).select_related("integration_instance"))
    if generation_id:
        gens = [g for g in gens if str(g.pk) == str(generation_id)]
        if not gens:
            raise Blocked("generation_not_current", "Choose a current, complete VSA snapshot of this customer.")
    if not gens:
        raise Blocked(
            "no_complete_generation", "No complete VSA snapshot exists for this customer yet. Run a sync first."
        )
    if len(gens) > 1:
        raise Blocked("generation_required", "This customer has several VSA instances; choose the snapshot.")
    gen = gens[0]
    if gen.hierarchy_status != "collected":
        raise Blocked(
            "hierarchy_incomplete",
            "The snapshot's site/group data is incomplete, so placement cannot be compared. Run a new sync.",
        )
    stale = bool(
        gen.published_at and gen.published_at < timezone.now() - timedelta(hours=settings.DATA_STALE_AFTER_HOURS)
    )
    if stale and not allow_stale:
        raise Blocked(
            "generation_stale",
            f"The snapshot is older than {settings.DATA_STALE_AFTER_HOURS} hours. Sync again, or acknowledge "
            "the stale source to compare anyway (every row will carry STALE_SOURCE).",
        )
    return gen, stale


def mapping_hash(sheet: str, header_row: int, mapping: dict[str, int]) -> str:
    return hashlib.sha256(json.dumps([sheet, header_row, mapping], sort_keys=True).encode()).hexdigest()


def request_run(
    user: Any,
    customer: Any,
    upload: ExpectedInventoryUpload,
    *,
    sheet: str,
    header_row: int,
    mapping: dict[str, Any],
    generation_id: Any,
    allow_stale: bool,
    request: Any,
) -> ReconciliationRun:
    try:
        gen, stale = choose_generation(customer, generation_id, allow_stale)
    except Blocked as exc:
        record_event(
            action="onboarding.run_blocked",
            outcome="denied",
            actor=user,
            customer=customer,
            target_type="onboarding_upload",
            target_id=str(upload.id),
            request=request,
            metadata={"code": exc.code},
        )
        raise
    workbook = load_workbook(upload)
    ws = workbook.sheet(sheet)
    clean = importer.validate_mapping(mapping, max(ws.width, len(importer.headers_for(ws, header_row))))
    importer.mapped_rows(ws, header_row, clean)  # validates header row + row limit before queueing
    run = ReconciliationRun.objects.create(
        customer=customer,
        upload=upload,
        upload_sha256=upload.sha256,
        upload_name=upload.display_name,
        sheet=sheet,
        header_row=header_row,
        mapping=clean,
        mapping_hash=mapping_hash(sheet, header_row, clean),
        logic_version=matching.LOGIC_VERSION,
        generation=gen,
        data_basis=gen.data_basis,
        stale_source_acknowledged=stale,
        requested_by=user,
    )
    record_event(
        action="onboarding.run_requested",
        outcome="success",
        actor=user,
        customer=customer,
        target_type="reconciliation_run",
        target_id=str(run.id),
        request=request,
        metadata={"generation": str(gen.pk), "stale_source": stale, "upload_sha256": upload.sha256},
    )
    from .tasks import run_reconciliation

    transaction.on_commit(lambda: run_reconciliation.delay(str(run.id)))
    return run


# ---------------------------------------------------------------------------------------------- worker


def load_devices(customer_id: Any, generation: DatasetGeneration) -> list[matching.Device]:
    """The pinned generation's devices for exactly this customer (customer + generation both filter)."""
    gen_filter = {"customer_id": customer_id, "generation": generation}
    orgs = dict(OrganizationNode.objects.filter(**gen_filter).values_list("external_id", "name"))
    sites = dict(SiteNode.objects.filter(**gen_filter).values_list("external_id", "name"))
    groups = dict(GroupNode.objects.filter(**gen_filter).values_list("external_id", "name"))
    macs: dict[Any, set[str]] = {}
    for obs_id, mac in (
        NetworkAdapterObservation.objects.filter(**gen_filter).exclude(mac="").values_list("observation_id", "mac")
    ):
        macs.setdefault(obs_id, set()).add(mac.upper())
    ips: dict[Any, set[str]] = {}
    for asset_id, addr in (
        IpAddressObservation.objects.filter(**gen_filter).exclude(address="").values_list("asset_id", "address")
    ):
        ips.setdefault(asset_id, set()).add(addr)
    from apps.patching.models import AppliedPolicyObservation

    policy_states = dict(
        AppliedPolicyObservation.objects.filter(**gen_filter).values_list("observation_id", "patch_state")
    )
    devices = []
    for o in AssetObservation.objects.filter(**gen_filter).select_related("asset").order_by("asset__external_id"):
        devices.append(
            matching.Device(
                asset_id=str(o.asset_id),
                external_id=o.asset.external_id,
                hostname=o.hostname,
                domain=o.domain,
                serial=o.serial_number,
                macs=frozenset(macs.get(o.pk, ())),
                ips=frozenset(ips.get(o.asset_id, ())),
                org_id=o.organization_external_id,
                org_name=orgs.get(o.organization_external_id, ""),
                site_id=o.site_external_id,
                site_name=o.site_name or sites.get(o.site_external_id, ""),
                group_id=o.group_external_id,
                group_name=groups.get(o.group_external_id, ""),
                last_seen_online=o.last_seen_online,
                is_agent_installed=o.is_agent_installed,
                network_status=o.network_status,
                patch_policy_state=policy_states.get(o.pk, "unknown"),
                client_version=o.client_version,
            )
        )
    return devices


def execute(run_id: str) -> ReconciliationRun:
    with transaction.atomic():
        run = ReconciliationRun.objects.select_for_update().select_related("customer", "requested_by").get(pk=run_id)
        if run.state != ReconciliationRun.State.QUEUED:
            return run
        run.state, run.started_at = ReconciliationRun.State.RUNNING, timezone.now()
        run.save(update_fields=["state", "started_at"])
    user = run.requested_by
    scope.invalidate_cache(user)
    if not user.is_active or not scope.has_customer_capability(user, run.customer_id, Cap.CUSTOMER_SYNC):
        return _fail(run, "authorization_revoked", "denied")
    gen = DatasetGeneration.objects.select_related("mapping").get(pk=run.generation_id)
    if gen.customer_id != run.customer_id or gen.mapping.mapping_status != "approved":
        return _fail(run, "mapping_not_approved")
    try:
        ws = load_workbook(run.upload).sheet(run.sheet)
        rows = importer.mapped_rows(ws, run.header_row, {k: int(v) for k, v in run.mapping.items()})
    except importer.ImportRejected as exc:
        return _fail(run, exc.code)
    from apps.inventory.health import effective_thresholds

    th = effective_thresholds(run.customer_id)
    params = matching.Params(
        snapshot_at=gen.published_at or gen.created_at,
        offline_hours=th.offline_hours,
        stale_agent_days=th.stale_days,
        stale_source=run.stale_source_acknowledged,
        minimum_agent_version=th.minimum_agent_version,
        thresholds_source=th.source,
    )
    try:
        outcome = matching.reconcile(rows, load_devices(run.customer_id, gen), params)
        _persist(run, outcome)
    except Exception:
        logger.exception("onboarding_run_failed", extra={"run_id": str(run.id)})
        return _fail(run, "reconciliation_failed")
    record_event(
        action="onboarding.run_completed",
        outcome="success",
        actor=user,
        customer=run.customer,
        target_type="reconciliation_run",
        target_id=str(run.id),
        metadata={"rows": outcome.summary["expected_rows"], "classifications": outcome.summary["classifications"]},
    )
    return run


def _persist(run: ReconciliationRun, outcome: matching.Outcome) -> None:
    objs = []
    for r in outcome.rows:
        objs.append(
            ReconciliationResult(
                run=run,
                customer_id=run.customer_id,
                kind=ReconciliationResult.Kind.EXPECTED,
                row_number=r.row_number,
                input=r.input,
                classification=r.classification,
                flags=r.flags,
                evidence=r.evidence,
                candidate_asset_ids=[d.asset_id for d in r.candidates],
                asset_id=r.device.asset_id if r.device else None,
                actual=r.device.placement() if r.device else {},
                review_state=(
                    ReconciliationResult.ReviewState.PENDING
                    if r.classification in ("AMBIGUOUS", "REVIEW_WRONG_ORGANIZATION")
                    else ReconciliationResult.ReviewState.NOT_REQUIRED
                ),
            )
        )
    for device, pending_row in outcome.unexpected:
        objs.append(
            ReconciliationResult(
                run=run,
                customer_id=run.customer_id,
                kind=ReconciliationResult.Kind.UNEXPECTED,
                asset_id=device.asset_id,
                actual={**device.placement(), "agent_installed": device.is_agent_installed},
                pending_review_row=pending_row,
            )
        )
    with transaction.atomic():
        ReconciliationResult.objects.bulk_create(objs, batch_size=1000)
        run.summary = {
            **outcome.summary,
            "generation": {
                "id": str(run.generation_id),
                "published_at": run.generation.published_at.isoformat() if run.generation.published_at else "",
                "data_basis": run.data_basis,
            },
        }
        run.parameters = outcome.summary["parameters"]
        run.state, run.completed_at = ReconciliationRun.State.COMPLETED, timezone.now()
        run.save(update_fields=["summary", "parameters", "state", "completed_at"])


def _fail(run: ReconciliationRun, code: str, outcome: str = "failure") -> ReconciliationRun:
    run.state, run.error_code, run.completed_at = ReconciliationRun.State.FAILED, code, timezone.now()
    run.save(update_fields=["state", "error_code", "completed_at"])
    record_event(
        action="onboarding.run_completed",
        outcome=outcome,
        actor=run.requested_by,
        customer=run.customer,
        target_type="reconciliation_run",
        target_id=str(run.id),
        metadata={"error_code": code},
    )
    return run


# ---------------------------------------------------------------------------------------------- review


class ReviewError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def review(
    result: ReconciliationResult, user: Any, decision: str, asset_id: str | None, note: str, request: Any
) -> ReconciliationResult:
    """One-time operator decision; the engine's classification/evidence stay untouched (immutable history)."""
    with transaction.atomic():
        result = ReconciliationResult.objects.select_for_update().select_related("run").get(pk=result.pk)
        if result.kind != "expected" or result.review_state != ReconciliationResult.ReviewState.PENDING:
            raise ReviewError("This row does not await review.")
        if result.classification == "AMBIGUOUS":
            if decision == "match":
                if not asset_id or asset_id not in result.candidate_asset_ids:
                    raise ReviewError("Choose one of the listed candidate devices.")
                device = next(
                    d for d in load_devices(result.customer_id, result.run.generation) if d.asset_id == asset_id
                )
                cls, _ = matching.classify_match(device, result.input)
                result.reviewed_classification, result.reviewed_asset_id = cls, asset_id
            elif decision == "no_match":
                result.reviewed_classification = "NOT_FOUND_IN_COMPLETE_SNAPSHOT"
            else:
                raise ReviewError("Decision must be 'match' or 'no_match'.")
        elif result.classification == "REVIEW_WRONG_ORGANIZATION":
            if decision == "confirm":
                result.reviewed_classification = "REVIEW_WRONG_ORGANIZATION"
                result.reviewed_asset_id = result.asset_id
            elif decision == "no_match":
                result.reviewed_classification = "NOT_FOUND_IN_COMPLETE_SNAPSHOT"
            else:
                raise ReviewError("Decision must be 'confirm' or 'no_match'.")
        result.review_state = ReconciliationResult.ReviewState.DECIDED
        result.reviewed_by, result.reviewed_at, result.review_note = user, timezone.now(), note[:500]
        result.save(
            update_fields=[
                "review_state",
                "reviewed_classification",
                "reviewed_asset",
                "reviewed_by",
                "reviewed_at",
                "review_note",
            ]
        )
    record_event(
        action="onboarding.row_reviewed",
        outcome="success",
        actor=user,
        customer=result.customer_id,
        target_type="reconciliation_result",
        target_id=str(result.id),
        request=request,
        metadata={"decision": decision, "classification": result.reviewed_classification},
    )
    return result
