"""VSA3-04 applied patch policies: budgeted collection, carry-forward, definitions, expected-baseline drift.

Facts are kept apart (docs/VSA_DATA_DICTIONARY.md): a policy *assignment* or *configuration* is never evidence that a
patch was deployed (``PATCH_POLICY_PRESENT`` ≠ ``PATCH_DEPLOYMENT_SUCCEEDED``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from django.db import transaction
from django.db.models import F, Max, OuterRef, Subquery
from django.utils import timezone

from apps.integrations.vsa.schema import PATCH_POLICY_TYPE, AppliedPolicyItem, PatchPolicyDefinitionData

from .models import (
    AppliedPolicy,
    AppliedPolicyObservation,
    ExpectedPatchPolicy,
    PatchPolicyDefinition,
    PatchPolicyState,
    UpdateStatus,
)

MAX_DEFINITIONS_PER_SYNC = 200


# ---------------------------------------------------------------------------------------------- collection


def ensure_observations(generation: Any) -> int:
    """One ``not_requested`` row per device of the generation (idempotent)."""
    from apps.inventory.models import AssetObservation

    existing = set(
        AppliedPolicyObservation.objects.filter(generation=generation).values_list("observation_id", flat=True)
    )
    rows = [
        AppliedPolicyObservation(
            observation_id=o.pk,
            customer_id=o.customer_id,
            asset_id=o.asset_id,
            generation_id=generation.pk,
            status=UpdateStatus.NOT_REQUESTED,
        )
        for o in AssetObservation.objects.filter(generation=generation).only("pk", "customer_id", "asset_id")
        if o.pk not in existing
    ]
    AppliedPolicyObservation.objects.bulk_create(rows, batch_size=1000)
    return len(rows)


def pending(generation: Any, limit: int) -> list[AppliedPolicyObservation]:
    """Devices not yet fetched this generation: never-collected first, then least recently collected (rotation)."""
    if limit <= 0:
        return []
    last = (
        AppliedPolicyObservation.objects.filter(asset_id=OuterRef("asset_id"), status=UpdateStatus.COLLECTED)
        .exclude(generation_id=generation.id)
        .values("asset_id")
        .annotate(m=Max("collected_at"))
        .values("m")
    )
    return list(
        AppliedPolicyObservation.objects.filter(generation=generation, status=UpdateStatus.NOT_REQUESTED)
        .annotate(last=Subquery(last))
        .select_related("asset")
        .order_by(F("last").asc(nulls_first=True), "asset__external_id")[:limit]
    )


def _derive(items: Iterable[AppliedPolicyItem]) -> tuple[str, str, str]:
    patch = [i for i in items if i.policy_type == PATCH_POLICY_TYPE]
    if not patch:
        return PatchPolicyState.NOT_REPORTED, "", ""
    first = patch[0]
    if first.explicit_none:
        return PatchPolicyState.EXPLICIT_NONE, "", first.policy_name
    return PatchPolicyState.ASSIGNED, first.policy_id, first.policy_name


def _write(po: AppliedPolicyObservation, items: Iterable[AppliedPolicyItem]) -> None:
    AppliedPolicy.objects.bulk_create(
        [
            AppliedPolicy(
                policy_observation=po,
                customer_id=po.customer_id,
                asset_id=po.asset_id,
                generation_id=po.generation_id,
                policy_type=i.policy_type,
                policy_id=i.policy_id,
                policy_name=i.policy_name,
                profiles=[{"id": p[0], "name": p[1], "category": p[2]} for p in i.profiles],
            )
            for i in items
        ]
    )


def record(po: AppliedPolicyObservation, items: tuple[AppliedPolicyItem, ...]) -> None:
    state, pid, name = _derive(items)
    with transaction.atomic():
        _write(po, items)
        po.status, po.collected_at = UpdateStatus.COLLECTED, timezone.now()
        po.patch_state, po.patch_policy_id, po.patch_policy_name = state, pid, name
        po.save(update_fields=["status", "collected_at", "patch_state", "patch_policy_id", "patch_policy_name"])


def record_failure(po: AppliedPolicyObservation) -> None:
    AppliedPolicyObservation.objects.filter(pk=po.pk).update(status=UpdateStatus.FAILED)


def carry_forward(generation: Any) -> int:
    """Devices not fetched this run keep their last successful response (its timestamp is preserved)."""
    carried = 0
    for po in AppliedPolicyObservation.objects.filter(generation=generation, status=UpdateStatus.NOT_REQUESTED):
        prev = (
            AppliedPolicyObservation.objects.filter(asset_id=po.asset_id, status=UpdateStatus.COLLECTED)
            .exclude(generation_id=generation.id)
            .order_by("-collected_at")
            .first()
        )
        if prev is None:
            continue
        with transaction.atomic():
            AppliedPolicy.objects.bulk_create(
                [
                    AppliedPolicy(
                        policy_observation=po,
                        customer_id=po.customer_id,
                        asset_id=po.asset_id,
                        generation_id=po.generation_id,
                        policy_type=r.policy_type,
                        policy_id=r.policy_id,
                        policy_name=r.policy_name,
                        profiles=r.profiles,
                    )
                    for r in prev.policies.all()
                ]
            )
            po.status, po.collected_at = UpdateStatus.CARRIED_FORWARD, prev.collected_at
            po.patch_state, po.patch_policy_id, po.patch_policy_name = (
                prev.patch_state,
                prev.patch_policy_id,
                prev.patch_policy_name,
            )
            po.save(update_fields=["status", "collected_at", "patch_state", "patch_policy_id", "patch_policy_name"])
        carried += 1
    return carried


def referenced_policy_ids(generation: Any) -> list[str]:
    ids = (
        AppliedPolicy.objects.filter(generation=generation, policy_type=PATCH_POLICY_TYPE)
        .exclude(policy_id="")
        .values_list("policy_id", flat=True)
        .distinct()
    )
    return sorted(set(ids), key=lambda x: int(x))[:MAX_DEFINITIONS_PER_SYNC]


def content_hash(d: PatchPolicyDefinitionData) -> str:
    canonical = json.dumps(
        [d.name, d.description, d.general_settings, d.os_rules, d.software_rules], sort_keys=True, default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def record_definition(generation: Any, d: PatchPolicyDefinitionData) -> None:
    PatchPolicyDefinition.objects.update_or_create(
        generation=generation,
        policy_id=d.policy_id,
        defaults={
            "customer_id": generation.customer_id,
            "status": PatchPolicyDefinition.Status.COLLECTED,
            "name": d.name,
            "description": d.description,
            "general_settings": d.general_settings,
            "os_rules": d.os_rules,
            "software_rules": d.software_rules,
            "content_hash": content_hash(d),
            "fetched_at": timezone.now(),
        },
    )


def record_definition_failure(generation: Any, policy_id: str) -> None:
    PatchPolicyDefinition.objects.update_or_create(
        generation=generation,
        policy_id=policy_id,
        defaults={
            "customer_id": generation.customer_id,
            "status": PatchPolicyDefinition.Status.FAILED,
            "fetched_at": timezone.now(),
        },
    )


# ---------------------------------------------------------------------------------------------- drift


class Drift:
    NO_BASELINE = "no_baseline"
    UNKNOWN = "unknown"
    MATCHES = "matches"
    DIFFERENT_POLICY = "different_policy"
    MISSING_POLICY = "missing_policy"
    UNEXPECTED_POLICY = "unexpected_policy"

    ALL = (NO_BASELINE, UNKNOWN, MATCHES, DIFFERENT_POLICY, MISSING_POLICY, UNEXPECTED_POLICY)
    LABELS = {
        NO_BASELINE: "No approved expectation covers this device",
        UNKNOWN: "Assignment unknown (not collected or no Patch Management entry)",
        MATCHES: "Matches the approved expectation",
        DIFFERENT_POLICY: "A different policy is assigned",
        MISSING_POLICY: "Expected a policy; No Policy is explicitly configured",
        UNEXPECTED_POLICY: "Expected no policy; a policy is assigned",
    }


def approved_baselines(customer_id: Any) -> dict[tuple[str, str], ExpectedPatchPolicy]:
    return {
        (b.scope_type, b.scope_external_id): b
        for b in ExpectedPatchPolicy.objects.filter(customer_id=customer_id, state=ExpectedPatchPolicy.State.APPROVED)
    }


def baseline_for(
    baselines: dict[tuple[str, str], ExpectedPatchPolicy], org_id: str, site_id: str, group_id: str
) -> ExpectedPatchPolicy | None:
    for key in (("group", group_id), ("site", site_id), ("organization", org_id)):
        if key[1] and key in baselines:
            return baselines[key]
    return None


def drift(baseline: ExpectedPatchPolicy | None, patch_state: str, policy_id: str) -> str:
    if baseline is None:
        return Drift.NO_BASELINE
    if patch_state in (PatchPolicyState.UNKNOWN, PatchPolicyState.NOT_REPORTED):
        return Drift.UNKNOWN
    if baseline.expect_no_policy:
        return Drift.MATCHES if patch_state == PatchPolicyState.EXPLICIT_NONE else Drift.UNEXPECTED_POLICY
    if patch_state == PatchPolicyState.EXPLICIT_NONE:
        return Drift.MISSING_POLICY
    return Drift.MATCHES if policy_id == baseline.expected_policy_id else Drift.DIFFERENT_POLICY
