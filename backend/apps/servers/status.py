"""SRV-01: which devices are servers, who owns them, and what each needs (patching/upgrade) from collected evidence.

Every figure comes from the customer's own current snapshot (or the generations a report pinned). "Not collected" is
never read as "nothing missing": a server whose OS update section was not collected shows that state and is not
counted as up to date.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from types import SimpleNamespace
from typing import Any

from django.db.models import Q
from django.utils import timezone

NOT_SEEN_DAYS = 30
ATTENTION_POLICY_STATES = ("explicit_none", "not_reported")


def detected(os_name: str) -> bool:
    return "server" in (os_name or "").casefold()


def server_source(os_name: str, is_server: bool | None) -> str:
    """'marked' | 'detected' | 'excluded' (marked not a server) | '' (not a server)."""
    if is_server is True:
        return "marked"
    if is_server is False:
        return "excluded" if detected(os_name) else ""
    return "detected" if detected(os_name) else ""


def rows(
    customer_id: Any, *, include_all: bool = False, generation_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """One row per server (or per device with ``include_all``) with owner and patch/upgrade evidence."""
    from apps.inventory.models import AssetObservation
    from apps.inventory.queries import current_generations
    from apps.patching.models import AppliedPolicyObservation, DeviceOsUpdate, PatchObservation
    from apps.software import lifecycle
    from apps.software.models import ComplianceResult

    from .models import ServerDesignation

    if generation_ids is None:
        gens = [str(g) for g in current_generations(customer_id).values_list("id", flat=True)]
    else:
        gens = list(generation_ids)
    observations = AssetObservation.objects.filter(customer_id=customer_id, generation_id__in=gens)
    designations = {
        str(d.asset_id): d
        for d in ServerDesignation.objects.filter(customer_id=customer_id).select_related("owner_group")
    }
    if not include_all:
        # Pre-filter in the database (P5-06): detected by name, or marked. ``server_source`` below decides.
        marked = [d.asset_id for d in designations.values() if d.is_server]
        observations = observations.filter(Q(os_name__icontains="server") | Q(asset_id__in=marked))
    observations = observations.values(
        "asset_id",
        "hostname",
        "os_name",
        "os_version",
        "site_name",
        "site_external_id",
        "group_name",
        "last_seen_online",
    )
    selected = []
    for values in observations.order_by("hostname", "id"):
        obs = SimpleNamespace(**values)
        d = designations.get(str(obs.asset_id))
        source = server_source(obs.os_name, d.is_server if d else None)
        if include_all or source in ("marked", "detected"):
            selected.append((obs, d, source))
    if not selected:
        return []
    # Every device of the snapshot needs no ID list (a 100k-entry IN clause is slower than none).
    asset_ids = None if include_all else [o.asset_id for o, _, _ in selected]
    scoped = {} if asset_ids is None else {"asset_id__in": asset_ids}

    patch = {
        str(a): (status, count)
        for a, status, count in PatchObservation.objects.filter(
            customer_id=customer_id, generation_id__in=gens, **scoped
        ).values_list("asset_id", "available_status", "available_count")
    }
    severity: dict[str, Counter[str]] = {}
    for a, sev in DeviceOsUpdate.objects.filter(
        customer_id=customer_id, generation_id__in=gens, **scoped, state=DeviceOsUpdate.State.AVAILABLE
    ).values_list("asset_id", "severity"):
        severity.setdefault(str(a), Counter())[(sev or "Unspecified").capitalize()] += 1
    policies = {
        str(a): (state, name)
        for a, state, name in AppliedPolicyObservation.objects.filter(
            customer_id=customer_id, generation_id__in=gens, **scoped
        ).values_list("asset_id", "patch_state", "patch_policy_name")
    }
    outdated = Counter(
        str(a)
        for a in ComplianceResult.objects.filter(
            customer_id=customer_id,
            evaluation__is_current=True,
            evaluation__generation_id__in=gens,
            **scoped,
            state="outdated",
        ).values_list("asset_id", flat=True)
    )
    today = timezone.now().date()
    life = {r["asset_id"]: r for r in lifecycle.os_rows(customer_id, today, generation_ids=gens, asset_ids=asset_ids)}
    now = timezone.now()

    out = []
    for obs, d, source in selected:
        aid = str(obs.asset_id)
        status, available = patch.get(aid, ("not_collected", None))
        sev = severity.get(aid, Counter())
        critical, important = sev.get("Critical", 0), sev.get("Important", 0)
        policy_state, policy_name = policies.get(aid, ("unknown", ""))
        lc = life.get(aid) or {}
        lc_status = lc.get("status", "unknown")
        eos = (lc.get("entry") or {}).get("end_of_support")
        reasons = []
        if critical:
            reasons.append(f"{critical} Critical OS update{'s' if critical != 1 else ''} available")
        if important:
            reasons.append(f"{important} Important OS update{'s' if important != 1 else ''} available")
        other = (available or 0) - critical - important if status in ("collected", "carried_forward") else 0
        if other > 0:
            reasons.append(f"{other} other OS update{'s' if other != 1 else ''} available")
        if policy_state in ATTENTION_POLICY_STATES:
            reasons.append("No patch policy assigned in VSA X")
        if lc_status == "end_of_support":
            reasons.append(f"Operating system out of support{f' since {eos}' if eos else ''} - upgrade needed")
        elif lc_status == "ending_soon":
            reasons.append(f"Operating system support ends {eos or 'soon'} - plan an upgrade")
        if outdated.get(aid):
            n = outdated[aid]
            reasons.append(f"{n} outdated program{'s' if n != 1 else ''}")
        days = (now - obs.last_seen_online).days if obs.last_seen_online else None
        if days is not None and days > NOT_SEEN_DAYS:
            reasons.append(f"Not seen for {days} days (updates cannot install)")
        group = d.owner_group if d else None
        out.append(
            {
                "asset_id": aid,
                "hostname": obs.hostname,
                "os_name": obs.os_name,
                "os_version": obs.os_version,
                "site": obs.site_name or obs.site_external_id,
                "vsa_group": obs.group_name,
                "last_seen_online": obs.last_seen_online.isoformat() if obs.last_seen_online else None,
                "server_source": source,
                "is_server": source in ("marked", "detected"),
                "note": d.note if d else "",
                "owner_group_id": str(group.id) if group else None,
                "owner_group": group.name if group else "",
                "owner_name": group.owner_name if group else "",
                "owner_email": group.owner_email if group else "",
                "os_updates_status": status,
                "updates_available": available if status in ("collected", "carried_forward") else None,
                "critical_available": critical,
                "important_available": important,
                "patch_policy_state": policy_state,
                "patch_policy": policy_name,
                "outdated_programs": outdated.get(aid, 0),
                "os_lifecycle": lc_status,
                "os_end_of_support": eos.isoformat() if isinstance(eos, dt.date) else (eos or None),
                "needs_attention": bool(reasons),
                "reasons": reasons,
            }
        )
    return out


def summary(data: list[dict[str, Any]]) -> dict[str, int]:
    """Totals over server rows (rows with ``is_server``); used by the Servers page, scorecard and customer summary."""
    servers = [r for r in data if r["is_server"]]
    return {
        "servers": len(servers),
        "needs_attention": sum(1 for r in servers if r["needs_attention"]),
        "unassigned": sum(1 for r in servers if not r["owner_group_id"]),
        "critical": sum(1 for r in servers if r["critical_available"]),
        "out_of_support": sum(1 for r in servers if r["os_lifecycle"] == "end_of_support"),
        "no_policy": sum(1 for r in servers if r["patch_policy_state"] in ATTENTION_POLICY_STATES),
    }
