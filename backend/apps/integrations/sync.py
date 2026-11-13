"""Safe sync engine: stage → validate → atomically publish (ARCHITECTURE.md §4, DATABASE.md §5).

* A run collects ONE approved mapping (one vendor organisation → one customer). Unmapped organisations are
  never requested; any record whose OrganizationId differs from the mapping is quarantined.
* Every page is committed together with its checkpoint (``next_skip``), so an interrupted run resumes from the
  last committed page and replays are idempotent (unique (asset, generation) and (asset, generation, row_hash)).
* The new generation becomes current only if the crawl completed and consistency checks pass; otherwise the
  previous published generation stays current and the run is marked ``partial`` (resumable) or ``failed``.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.models import Customer, CustomerSourceMapping
from apps.inventory.ingest import collect_hierarchy, record_details
from apps.patching.ingest import (
    carry_forward,
    pending_installed,
    record_installed,
    record_installed_failure,
    record_list_sections,
)

from .http import ConnectorError, VendorAuthError, VendorRateLimited, VendorUnavailable
from .models import DatasetGeneration, IntegrationInstance, SyncQuarantine, SyncRun
from .secrets import CredentialUnavailable
from .vsa.adapter import AssetPage, VsaXAdapter, validate_org_id
from .vsa.schema import PageInvalid, RecordInvalid, VsaAsset, normalize_asset, normalize_installed_updates

logger = logging.getLogger("portal.sync")

DATASET_VSA_ASSETS = "vsa_assets"
MAX_ATTEMPTS = 5

AdapterFactory = Callable[[IntegrationInstance], VsaXAdapter]


class SyncRefused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class InstanceBusy(Exception):
    pass


class ConsistencyError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------------------------- requesting


def _preflight(mapping: CustomerSourceMapping) -> None:
    if mapping.mapping_status != CustomerSourceMapping.Status.APPROVED:
        raise SyncRefused("mapping_not_approved", "Only approved source mappings can be synchronised.")
    instance = mapping.integration_instance
    if instance.provider != IntegrationInstance.Provider.VSA_X:
        raise SyncRefused("provider_not_supported", "Only VSA X collection is implemented.")
    if not instance.enabled:
        raise SyncRefused("integration_disabled", "The integration instance is disabled.")
    customer = mapping.customer
    if customer.status not in (Customer.Status.ACTIVE, Customer.Status.ONBOARDING):
        raise SyncRefused("customer_inactive", "Customer is suspended or archived.")
    if customer.restricted_data:
        raise SyncRefused(
            "restricted_customer", "Restricted-data customers require a separately approved deployment (SECURITY §6)."
        )
    try:
        validate_org_id(mapping.external_org_id)
    except ValueError as exc:
        raise SyncRefused("invalid_external_org_id", str(exc)) from exc


def request_sync(
    mapping: CustomerSourceMapping,
    *,
    requested_by: Any,
    trigger: str = SyncRun.Trigger.MANUAL,
    idempotency_key: str | None = None,
) -> tuple[SyncRun, bool]:
    """Create (or return the existing active) run for the mapping's scope. Returns (run, created)."""
    _preflight(mapping)
    if idempotency_key:
        existing = SyncRun.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            if existing.mapping_id != mapping.id:
                raise SyncRefused("idempotency_conflict", "Idempotency key already used for another scope.")
            return existing, False
    active = SyncRun.objects.filter(
        integration_instance=mapping.integration_instance,
        customer=mapping.customer,
        dataset=DATASET_VSA_ASSETS,
        state__in=SyncRun.ACTIVE_STATES,
    ).first()
    if active is not None:
        return active, False
    try:
        with transaction.atomic():
            run = SyncRun.objects.create(
                integration_instance=mapping.integration_instance,
                customer=mapping.customer,
                mapping=mapping,
                dataset=DATASET_VSA_ASSETS,
                trigger=trigger,
                requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
                idempotency_key=idempotency_key or f"{mapping.id}:{uuid.uuid4().hex}",
            )
    except IntegrityError:
        run = SyncRun.objects.get(
            integration_instance=mapping.integration_instance,
            customer=mapping.customer,
            dataset=DATASET_VSA_ASSETS,
            state__in=SyncRun.ACTIVE_STATES,
        )
        return run, False
    record_event(
        action="sync.requested",
        outcome="success",
        actor=requested_by,
        customer=mapping.customer,
        target_type="sync_run",
        target_id=str(run.id),
        metadata={"integration": str(mapping.integration_instance_id), "trigger": trigger},
    )
    from .tasks import run_sync

    transaction.on_commit(lambda: run_sync.delay(str(run.id)))
    return run, True


# ---------------------------------------------------------------------------------------------- executing


def default_adapter_factory(instance: IntegrationInstance) -> VsaXAdapter:
    return VsaXAdapter(instance)


def execute(run_id: str, *, adapter_factory: AdapterFactory = default_adapter_factory) -> SyncRun:
    run = _begin(run_id)
    if run.state != SyncRun.State.RUNNING:
        return run
    generation = run.generation
    assert generation is not None  # noqa: S101
    try:
        adapter = adapter_factory(run.integration_instance)
        for page in adapter.iter_asset_pages(run.mapping.external_org_id, start_skip=run.next_skip):
            _ingest_page(run, generation, page)
        _collect_installed_updates(run, generation, adapter)
        _collect_applied_policies(run, generation, adapter)
        collect_hierarchy(run, generation, adapter)
        _finalize(run, generation)
    except VendorAuthError:
        return _fail(run, "auth_failed", instance_status=IntegrationInstance.Status.FAILED)
    except (VendorRateLimited, VendorUnavailable) as exc:
        return _pause(run, exc.code)
    except ConsistencyError as exc:
        return _fail(run, exc.code)
    except (ConnectorError, PageInvalid, CredentialUnavailable) as exc:
        code = getattr(exc, "code", None) or (
            "credential_unavailable" if isinstance(exc, CredentialUnavailable) else "malformed_page"
        )
        return _fail(run, code, instance_status=IntegrationInstance.Status.FAILED)
    except Exception:
        logger.exception("sync_internal_error", extra={"sync_run_id": str(run.id)})
        return _fail(run, "internal_error")
    return run


def _begin(run_id: str) -> SyncRun:
    with transaction.atomic():
        run = (
            SyncRun.objects.select_for_update(of=("self",))
            .select_related("integration_instance", "customer", "mapping", "requested_by", "generation")
            .get(pk=run_id)
        )
        if run.state not in (SyncRun.State.QUEUED, SyncRun.State.PARTIAL):
            return run  # completed/failed/running elsewhere: idempotent no-op
        # Re-validate everything in the worker: mapping may have been revoked, requester may have lost access.
        run.mapping.refresh_from_db()
        run.customer.refresh_from_db()
        run.integration_instance.refresh_from_db()
        refusal = None
        if (
            run.mapping.customer_id != run.customer_id
            or run.mapping.integration_instance_id != run.integration_instance_id
        ):
            refusal = "mapping_scope_changed"
        else:
            try:
                _preflight(run.mapping)
            except SyncRefused as exc:
                refusal = exc.code
        if refusal is None and run.trigger == SyncRun.Trigger.MANUAL:
            requester = run.requested_by
            if requester is None:
                refusal = "requester_missing"
            else:
                scope.invalidate_cache(requester)
                if not scope.has_customer_capability(requester, run.customer_id, Cap.CUSTOMER_SYNC):
                    refusal = "authorization_revoked"
        if refusal is not None:
            return _fail(run, refusal, outcome="denied")
        if run.attempts >= MAX_ATTEMPTS:
            return _fail(run, "retry_budget_exhausted")

    try:
        with transaction.atomic():
            run = SyncRun.objects.select_for_update().get(pk=run_id)
            run.state = SyncRun.State.RUNNING
            run.attempts += 1
            run.started_at = run.started_at or timezone.now()
            if run.generation_id is None:
                run.generation = DatasetGeneration.objects.create(
                    integration_instance_id=run.integration_instance_id,
                    customer_id=run.customer_id,
                    mapping_id=run.mapping_id,
                    dataset=run.dataset,
                    data_basis="fixture" if run.integration_instance.is_fixture else "live",
                )
            run.save()
    except IntegrityError as exc:  # another run for this instance is already calling the vendor
        raise InstanceBusy(str(run_id)) from exc
    IntegrationInstance.objects.filter(pk=run.integration_instance_id).update(status=IntegrationInstance.Status.RUNNING)
    return SyncRun.objects.select_related("integration_instance", "customer", "mapping", "generation").get(pk=run_id)


def _quarantine(run: SyncRun, reason: str, raw: dict[str, Any] | None, asset: VsaAsset | None = None) -> None:
    ext_id = asset.identifier if asset else str((raw or {}).get("Identifier", ""))[:128]
    org_id = asset.organization_id if asset else str((raw or {}).get("OrganizationId", ""))[:128]
    name = asset.name if asset else str((raw or {}).get("Name", ""))[:255]
    SyncQuarantine.objects.create(
        sync_run=run,
        integration_instance_id=run.integration_instance_id,
        external_id=ext_id,
        external_org_id=org_id,
        reason=reason,
        snapshot={"Identifier": ext_id, "Name": name, "OrganizationId": org_id},
    )


def _ingest_page(run: SyncRun, generation: DatasetGeneration, page: AssetPage) -> None:
    from apps.inventory.models import Asset, AssetObservation
    from apps.software.models import SoftwareInstallation

    now = timezone.now()
    if page.total_count is None:
        raise ConsistencyError("missing_total_count")
    if run.initial_total_count is not None and page.total_count != run.initial_total_count:
        # Records were added/removed while paging with $skip: positions shifted, so pages may overlap or miss rows.
        raise ConsistencyError("source_changed_during_crawl")
    with transaction.atomic():
        fetched = quarantined = 0
        for raw in page.records:
            fetched += 1
            try:
                asset_data = normalize_asset(raw)
            except RecordInvalid as exc:
                _quarantine(run, exc.reason, raw)
                quarantined += 1
                continue
            if asset_data.organization_id != run.mapping.external_org_id:
                _quarantine(run, "organization_mismatch", raw, asset_data)
                quarantined += 1
                continue
            asset, _ = Asset.objects.get_or_create(
                integration_instance_id=run.integration_instance_id,
                external_id=asset_data.identifier,
                defaults={"customer_id": run.customer_id},
            )
            if asset.customer_id != run.customer_id:
                _quarantine(run, "customer_conflict", raw, asset_data)
                quarantined += 1
                continue
            software = asset_data.installed_software
            observation, created = AssetObservation.objects.get_or_create(
                asset=asset,
                generation=generation,
                defaults={
                    "customer_id": run.customer_id,
                    "hostname": asset_data.name,
                    "description": asset_data.description,
                    "device_type": asset_data.device_type,
                    "group_name": asset_data.group_name,
                    "site_external_id": asset_data.site_id,
                    "organization_external_id": asset_data.organization_id,
                    "computer_id": asset_data.computer_id,
                    "client_version": asset_data.client_version,
                    "last_seen_online": asset_data.last_seen_online,
                    "os_name": asset_data.os_name,
                    "os_version": asset_data.os_version,
                    "manufacturer": asset_data.manufacturer,
                    "model": asset_data.model,
                    "serial_number": asset_data.serial_number,
                    "domain": asset_data.domain,
                    "tags": list(asset_data.tags),
                    "memory_total_raw": asset_data.memory_total_raw,
                    "cpu_name": asset_data.cpu_name,
                    "cpu_cores_raw": asset_data.cpu_cores_raw,
                    "logical_processors_raw": asset_data.logical_processors_raw,
                    "firewall_enabled": asset_data.firewall_enabled,
                    "uac_enabled": asset_data.uac_enabled,
                    "antivirus_enabled_raw": asset_data.antivirus_enabled_raw,
                    "antivirus_up_to_date_raw": asset_data.antivirus_up_to_date_raw,
                    "software_status": (
                        AssetObservation.SoftwareStatus.NOT_COLLECTED
                        if software is None
                        else AssetObservation.SoftwareStatus.COLLECTED
                    ),
                    "software_count": None if software is None else len(software),
                    "collected_at": now,
                },
            )
            if not created:
                continue  # replayed page or duplicate across pages: idempotent
            record_list_sections(observation, asset_data)
            record_details(observation, asset_data)
            if software:
                seen: Counter[tuple[str, str, str]] = Counter()
                rows = []
                for item in software:
                    key = (item.name, item.publisher, item.version)
                    seen[key] += 1
                    digest = hashlib.sha256("\x1f".join((*key, str(seen[key]))).encode()).hexdigest()
                    rows.append(
                        SoftwareInstallation(
                            customer_id=run.customer_id,
                            asset=asset,
                            observation=observation,
                            generation=generation,
                            raw_name=item.name,
                            raw_publisher=item.publisher,
                            raw_version=item.version,
                            row_hash=digest,
                        )
                    )
                SoftwareInstallation.objects.bulk_create(rows, ignore_conflicts=True)
        SyncRun.objects.filter(pk=run.pk).update(
            next_skip=page.skip + len(page.records),
            pages_fetched=run.pages_fetched + 1,
            fetched_count=run.fetched_count + fetched,
            quarantined_count=run.quarantined_count + quarantined,
            source_total_count=page.total_count,
            initial_total_count=page.total_count if run.initial_total_count is None else run.initial_total_count,
            api_requests=run.api_requests + 1,
        )
    run.refresh_from_db()


def _collect_installed_updates(run: SyncRun, generation: DatasetGeneration, adapter: VsaXAdapter) -> None:
    """Budgeted per-device ``GET /api/v3/assets/:id?include=InstalledUpdates`` (only documented source).

    Auth/rate-limit/unavailable errors propagate (fail or pause the run); a per-device 4xx or malformed body
    marks only that device ``failed``. Devices outside the budget keep ``not_requested`` and are carried forward.
    """
    from .http import VendorClientError

    budget = run.integration_instance.installed_updates_budget
    remaining = max(0, budget - run.installed_updates_requested)
    for po in pending_installed(generation, remaining):
        SyncRun.objects.filter(pk=run.pk).update(
            installed_updates_requested=F("installed_updates_requested") + 1, api_requests=F("api_requests") + 1
        )
        try:
            body = adapter.get_installed_updates(po.asset.external_id)
            record_installed(po, normalize_installed_updates(body, po.asset.external_id))
        except (VendorClientError, RecordInvalid, ValueError):
            record_installed_failure(po)
    carry_forward(generation)
    run.refresh_from_db()


def _collect_applied_policies(run: SyncRun, generation: DatasetGeneration, adapter: VsaXAdapter) -> None:
    """VSA3-04: budgeted ``GET /devices/:id/appliedpolicies`` + one ``GET /patchmanagement/policies/:id`` per
    referenced policy. Per-device/per-policy 4xx or malformed bodies mark only that item ``failed``.
    """
    from apps.patching import policies

    from .http import VendorClientError
    from .vsa.schema import normalize_applied_policies, normalize_patch_policy

    policies.ensure_observations(generation)
    remaining = max(0, run.integration_instance.applied_policies_budget - run.applied_policies_requested)
    for po in policies.pending(generation, remaining):
        SyncRun.objects.filter(pk=run.pk).update(
            applied_policies_requested=F("applied_policies_requested") + 1, api_requests=F("api_requests") + 1
        )
        try:
            policies.record(po, normalize_applied_policies(adapter.get_applied_policies(po.asset.external_id)))
        except (VendorClientError, RecordInvalid, PageInvalid, ValueError):
            policies.record_failure(po)
    policies.carry_forward(generation)
    for policy_id in policies.referenced_policy_ids(generation):
        SyncRun.objects.filter(pk=run.pk).update(api_requests=F("api_requests") + 1)
        try:
            policies.record_definition(
                generation, normalize_patch_policy(adapter.get_patch_policy(policy_id), policy_id)
            )
        except (VendorClientError, RecordInvalid, ValueError):
            policies.record_definition_failure(generation, policy_id)
    run.refresh_from_db()


def _finalize(run: SyncRun, generation: DatasetGeneration) -> None:
    from apps.inventory.models import Asset, AssetObservation
    from apps.software.models import SoftwareInstallation

    observed_ids = list(
        AssetObservation.objects.filter(generation=generation).values_list("asset__external_id", flat=True)
    )
    quarantined_ids = set(
        SyncQuarantine.objects.filter(sync_run=run).exclude(external_id="").values_list("external_id", flat=True)
    )
    unidentified = SyncQuarantine.objects.filter(sync_run=run, external_id="").count()
    total = run.source_total_count
    if total is None:
        raise ConsistencyError("missing_total_count")
    unique_seen = len(set(observed_ids) | quarantined_ids) + unidentified
    if unique_seen != total:
        # Source changed during the crawl ($skip paging shifted) or pages were missed: never publish partially.
        raise ConsistencyError("count_mismatch")

    previous = DatasetGeneration.objects.filter(
        integration_instance_id=run.integration_instance_id,
        customer_id=run.customer_id,
        dataset=run.dataset,
        is_current=True,
    ).first()
    ratio = float(getattr(settings, "SYNC_MAX_DROP_RATIO", 0.5))
    if previous and previous.row_count >= 20 and len(observed_ids) < previous.row_count * (1 - ratio):
        raise ConsistencyError("row_count_drop_guard")

    with transaction.atomic():
        DatasetGeneration.objects.select_for_update().filter(
            integration_instance_id=run.integration_instance_id, customer_id=run.customer_id, dataset=run.dataset
        ).exclude(pk=generation.pk).filter(is_current=True).update(
            is_current=False, state=DatasetGeneration.State.SUPERSEDED
        )
        generation.state = DatasetGeneration.State.PUBLISHED
        generation.is_current = True
        generation.published_at = timezone.now()
        generation.row_count = len(observed_ids)
        generation.software_row_count = SoftwareInstallation.objects.filter(generation=generation).count()
        generation.source_total_count = total
        generation.validation_hash = hashlib.sha256("\n".join(sorted(observed_ids)).encode()).hexdigest()
        generation.save()
        scope_assets = Asset.objects.filter(
            integration_instance_id=run.integration_instance_id, customer_id=run.customer_id
        )
        scope_assets.filter(observations__generation=generation).update(active=True, last_generation=generation)
        # Tombstoning only after a complete, consistent inventory.
        scope_assets.exclude(observations__generation=generation).update(active=False)
        SyncRun.objects.filter(pk=run.pk).update(state=SyncRun.State.COMPLETED, ended_at=timezone.now(), error_code="")
        IntegrationInstance.objects.filter(pk=run.integration_instance_id).update(
            status=IntegrationInstance.Status.COMPLETED
        )
    run.refresh_from_db()
    record_event(
        action="sync.completed",
        outcome="success",
        actor_label="system:sync",
        customer=run.customer,
        target_type="sync_run",
        target_id=str(run.id),
        metadata={
            "generation": str(generation.id),
            "assets": generation.row_count,
            "quarantined": run.quarantined_count,
            "api_requests": run.api_requests,
        },
    )
    from apps.software.services import evaluate_generation

    try:
        evaluate_generation(generation)
    except Exception:  # published data stays valid; classification can be re-run
        logger.exception("compliance_evaluation_failed", extra={"generation_id": str(generation.id)})


def _pause(run: SyncRun, code: str) -> SyncRun:
    SyncRun.objects.filter(pk=run.pk).update(state=SyncRun.State.PARTIAL, error_code=code)
    IntegrationInstance.objects.filter(pk=run.integration_instance_id).update(status=IntegrationInstance.Status.PARTIAL)
    run.refresh_from_db()
    record_event(
        action="sync.paused",
        outcome="failure",
        actor_label="system:sync",
        customer=run.customer,
        target_type="sync_run",
        target_id=str(run.id),
        metadata={"error_code": code, "next_skip": run.next_skip},
    )
    return run


def _fail(run: SyncRun, code: str, *, outcome: str = "failure", instance_status: str | None = None) -> SyncRun:
    SyncRun.objects.filter(pk=run.pk).update(state=SyncRun.State.FAILED, error_code=code, ended_at=timezone.now())
    if run.generation_id:
        DatasetGeneration.objects.filter(pk=run.generation_id, state=DatasetGeneration.State.STAGED).update(
            state=DatasetGeneration.State.DISCARDED
        )
    if instance_status:
        IntegrationInstance.objects.filter(pk=run.integration_instance_id).update(status=instance_status)
    run.refresh_from_db()
    record_event(
        action="sync.failed",
        outcome=outcome,
        actor_label="system:sync",
        customer=run.customer,
        target_type="sync_run",
        target_id=str(run.id),
        metadata={"error_code": code},
    )
    return run
