"""VSA3-04 read model: patch-policy coverage, definitions and drift for one already-authorised customer."""

from __future__ import annotations

from collections import Counter
from typing import Any

from apps.inventory.models import GroupNode, OrganizationNode, SiteNode
from apps.inventory.queries import current_generations, current_observations

from .models import AppliedPolicyObservation, PatchPolicyDefinition, PatchPolicyState, UpdateStatus
from .policies import Drift, approved_baselines, baseline_for, drift

NOTE = (
    "Policy assignment and policy configuration come from VSA X. They describe what is configured, not what was "
    "deployed: an assigned policy is not evidence that any patch was installed."
)


def device_rows(customer_id: Any) -> list[dict[str, Any]]:
    """One row per device in the current generation(s); devices without a policy row are ``unknown``."""
    gens = list(current_generations(customer_id))
    pol = {
        p.observation_id: p
        for p in AppliedPolicyObservation.objects.filter(customer_id=customer_id, generation__in=gens)
    }
    groups = {
        (g.generation_id, g.external_id): g.name
        for g in GroupNode.objects.filter(customer_id=customer_id, generation__in=gens)
    }
    baselines = approved_baselines(customer_id)
    rows = []
    for o in current_observations(customer_id).order_by("hostname", "asset_id"):
        p = pol.get(o.pk)
        state = p.patch_state if p else PatchPolicyState.UNKNOWN
        status = p.status if p else "not_collected"
        policy_id = p.patch_policy_id if p else ""
        base = baseline_for(baselines, o.organization_external_id, o.site_external_id, o.group_external_id)
        rows.append(
            {
                "asset_id": str(o.asset_id),
                "hostname": o.hostname,
                "organization_external_id": o.organization_external_id,
                "site_external_id": o.site_external_id,
                "site_name": o.site_name,
                "group_external_id": o.group_external_id,
                "group_name": groups.get((o.generation_id, o.group_external_id), ""),
                "collection_status": status,
                "collected_at": p.collected_at.isoformat() if p and p.collected_at else None,
                "patch_state": state,
                "patch_policy_id": policy_id,
                "patch_policy_name": p.patch_policy_name if p else "",
                "expected": None
                if base is None
                else {
                    "scope_type": base.scope_type,
                    "scope_external_id": base.scope_external_id,
                    "expect_no_policy": base.expect_no_policy,
                    "policy_id": base.expected_policy_id,
                    "policy_name": base.expected_policy_name,
                },
                "drift": drift(base, state, policy_id),
            }
        )
    return rows


def definitions(customer_id: Any) -> list[dict[str, Any]]:
    gens = list(current_generations(customer_id))
    out = []
    for d in PatchPolicyDefinition.objects.filter(customer_id=customer_id, generation__in=gens).order_by("policy_id"):
        previous = (
            PatchPolicyDefinition.objects.filter(
                customer_id=customer_id, policy_id=d.policy_id, status=PatchPolicyDefinition.Status.COLLECTED
            )
            .exclude(generation__in=gens)
            .order_by("-fetched_at")
            .first()
        )
        out.append(
            {
                "policy_id": d.policy_id,
                "status": d.status,
                "name": d.name,
                "description": d.description,
                "general_settings": d.general_settings,
                "os_rules": d.os_rules,
                "software_rules": d.software_rules,
                "fetched_at": d.fetched_at.isoformat(),
                "changed_since_previous": None
                if previous is None or d.status != PatchPolicyDefinition.Status.COLLECTED
                else previous.content_hash != d.content_hash,
            }
        )
    return out


def summary(customer_id: Any) -> dict[str, Any]:
    rows = device_rows(customer_id)
    states = Counter(r["patch_state"] for r in rows)
    statuses = Counter(r["collection_status"] for r in rows)
    drifts = Counter(r["drift"] for r in rows)
    verified = states[PatchPolicyState.ASSIGNED] + states[PatchPolicyState.EXPLICIT_NONE]
    by_policy: Counter[tuple[str, str]] = Counter(
        (r["patch_policy_id"], r["patch_policy_name"]) for r in rows if r["patch_state"] == PatchPolicyState.ASSIGNED
    )
    gens = list(current_generations(customer_id))
    orgs = {
        o.external_id: o.name for o in OrganizationNode.objects.filter(customer_id=customer_id, generation__in=gens)
    }
    sites = {s.external_id: s.name for s in SiteNode.objects.filter(customer_id=customer_id, generation__in=gens)}
    return {
        "as_of": [g.published_at.isoformat() if g.published_at else None for g in gens],
        "data_basis": sorted({g.data_basis for g in gens}),
        "devices": len(rows),
        "patch_states": {s.value: states.get(s.value, 0) for s in PatchPolicyState},
        "collection_status": dict(sorted(statuses.items())),
        "coverage": {
            "assigned": states[PatchPolicyState.ASSIGNED],
            "verified_denominator": verified,
            "percent": round(100 * states[PatchPolicyState.ASSIGNED] / verified, 1) if verified else None,
            "excluded_unknown": len(rows) - verified,
            "definition": "assigned / devices whose assignment is verified (assigned or explicit No Policy); "
            "unknown and not-reported devices are excluded and shown separately",
        },
        "by_policy": [
            {"policy_id": pid, "policy_name": name, "devices": n} for (pid, name), n in by_policy.most_common()
        ],
        "drift": {k: drifts.get(k, 0) for k in Drift.ALL},
        "drift_labels": Drift.LABELS,
        "definitions": definitions(customer_id),
        "scopes": {
            "organizations": orgs,
            "sites": sites,
            "groups": {
                g.external_id: {"name": g.name, "site": g.site_external_id}
                for g in GroupNode.objects.filter(customer_id=customer_id, generation__in=gens)
            },
        },
        "carried_forward_note": "Devices marked carried_forward show their last successful response; see collected_at."
        if statuses.get(UpdateStatus.CARRIED_FORWARD)
        else "",
        "note": NOTE,
    }


def filter_rows(rows: list[dict[str, Any]], params: Any) -> list[dict[str, Any]]:
    if (state := params.get("patch_state")) and state in PatchPolicyState.values:
        rows = [r for r in rows if r["patch_state"] == state]
    if (d := params.get("drift")) and d in Drift.ALL:
        rows = [r for r in rows if r["drift"] == d]
    if pid := params.get("policy_id"):
        rows = [r for r in rows if r["patch_policy_id"] == pid[:20]]
    if gid := params.get("group_id"):
        rows = [r for r in rows if r["group_external_id"] == gid[:20]]
    if q := params.get("q", "").strip().casefold()[:100]:
        rows = [r for r in rows if q in r["hostname"].casefold()]
    return rows
