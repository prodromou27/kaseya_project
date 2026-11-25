"""All-customers overview (CRM-05): one row of key measures per customer the user may read.

Reuses the per-customer read models, so every figure equals the one on that customer's own pages. Only customers
the requesting user can read appear; nothing from other customers is summed or leaked.
"""

from __future__ import annotations

from typing import Any

MAX_CUSTOMERS = 200


def row(customer: Any) -> dict[str, Any]:
    from apps.compliance import engine
    from apps.compliance.models import ComplianceBaseline
    from apps.inventory import health
    from apps.inventory.queries import current_generations, stale_cutoff
    from apps.patching import queries as patching
    from apps.software import queries as software

    h = health.summary(customer.id)
    dims = h["dimensions"]
    os = patching.summary(customer.id)
    sw = software.summary(customer.id)
    gens = list(current_generations(customer.id))
    as_of = max((g.published_at for g in gens if g.published_at), default=None)
    scores = []
    baselines = list(ComplianceBaseline.objects.filter(customer=customer, enabled=True).prefetch_related("rules"))
    if baselines:
        facts = engine.load_facts(customer.id)
        scores = [s for s in (engine.evaluate(b, facts)["score_pct"] for b in baselines) if s is not None]
    return {
        "id": str(customer.id),
        "code": customer.code,
        "name": customer.name,
        "status": customer.status,
        "devices": h["devices"],
        "offline": sum(dims["connectivity"].get(k, 0) for k in ("offline", "stale", "never_seen")),
        "disk_critical": dims["disk"].get("critical", 0),
        "antivirus_issues": sum(dims["antivirus"].get(k, 0) for k in ("disabled", "enabled_outdated")),
        "critical_updates": os["devices_by_severity"].get("Critical", 0) if os["devices_reporting_updates"] else None,
        "outdated_software_devices": sw["unique_assets_with_outdated"] if sw["eligible_installations"] else None,
        "compliance_pct": round(min(scores), 1) if scores else None,
        "baselines": len(baselines),
        "as_of": as_of.isoformat() if as_of else None,
        "stale": as_of is None or as_of < stale_cutoff(),
    }


# PERF-03: each customer's row is cached under a key that changes whenever its inputs change (published
# generations, software evaluations, compliance baselines, approved thresholds, name/status), so a new sync or setting
# shows at once. The TTL only bounds time-relative figures (e.g. a device crossing the offline threshold).
CACHE_SECONDS = 600


def _version(customer: Any) -> str:
    import hashlib

    from django.db.models import Count, Max

    from apps.compliance.models import ComplianceBaseline
    from apps.inventory.models import HealthThresholds
    from apps.inventory.queries import current_generations
    from apps.software.queries import current_evaluations

    parts = (
        sorted((str(g), str(p)) for g, p in current_generations(customer.id).values_list("id", "published_at")),
        sorted(str(e) for e in current_evaluations(customer.id).values_list("id", flat=True)),
        ComplianceBaseline.objects.filter(customer=customer).aggregate(
            changed=Max("updated_at"), baselines=Count("id", distinct=True), rules=Count("rules")
        ),
        str(
            HealthThresholds.objects.filter(customer_id=customer.id, state=HealthThresholds.State.APPROVED)
            .values_list("id", flat=True)
            .first()
        ),
        customer.code,
        customer.name,
        customer.status,
    )
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:32]


def cached_row(customer: Any) -> dict[str, Any]:
    from django.core.cache import cache
    from django.utils.dateparse import parse_datetime

    from apps.inventory.queries import stale_cutoff

    key = f"okp:overview:v1:{customer.id}:{_version(customer)}"
    data = cache.get(key)
    if data is None:
        data = row(customer)
        cache.set(key, data, CACHE_SECONDS)
    as_of = parse_datetime(data["as_of"]) if data["as_of"] else None
    return {**data, "stale": as_of is None or as_of < stale_cutoff()}  # never cached: depends on the time now


def overview(customers: list[Any]) -> list[dict[str, Any]]:
    return [cached_row(c) for c in customers[:MAX_CUSTOMERS]]
