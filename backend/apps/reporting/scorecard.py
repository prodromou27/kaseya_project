"""Monthly customer scorecard (CRM-02): one row per measure across health, patching, software, lifecycle,
compliance and network, with the value ~30 days earlier where retained history allows it.

Current values come from the same read models as the portal pages. "30 days ago" uses retained published
generations (trends): the latest point on or before 30 days ago, otherwise the oldest point in the window, and the
date of that point is stated. Measures without history show no comparison rather than an invented one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

COLUMNS = ("section", "measure", "value", "previous_value", "previous_as_of", "change", "notes")


def _previous(customer_id: Any) -> dict[str, Any] | None:
    from .trends import trend_points

    points = trend_points(customer_id, 45)["points"]
    if not points:
        return None
    cutoff = timezone.now() - timedelta(days=30)
    before = [p for p in points if p["as_of"] <= cutoff]
    chosen = before[-1] if before else points[0]
    latest = points[-1]
    if chosen["generation_id"] == latest["generation_id"]:
        return None
    return chosen


def _change(now: Any, before: Any) -> str:
    if not isinstance(now, (int, float)) or not isinstance(before, (int, float)):
        return ""
    diff = now - before
    # Words, not "+2": a leading "+" is escaped by the spreadsheet formula-injection guard.
    return f"up {diff:g}" if diff > 0 else f"down {-diff:g}" if diff < 0 else "no change"


def rows(customer: Any) -> list[list[Any]]:
    from apps.compliance import engine
    from apps.compliance.models import ComplianceBaseline
    from apps.inventory import health, subnets
    from apps.patching import queries as patching
    from apps.software import lifecycle, thirdparty
    from apps.software import queries as software

    out: list[list[Any]] = []
    prev = _previous(customer.id)
    prev_at = prev["as_of"].date().isoformat() if prev else ""

    def add(section: str, measure: str, value: Any, previous: Any = None, notes: str = "") -> None:
        has_prev = previous is not None
        out.append(
            [
                section,
                measure,
                "" if value is None else value,
                "" if not has_prev else previous,
                prev_at if has_prev else "",
                _change(value, previous) if has_prev else "",
                notes,
            ]
        )

    h = health.summary(customer.id)
    dims = h["dimensions"]
    add("Inventory", "Devices", h["devices"], prev["devices"] if prev else None)
    add(
        "Health",
        "Offline, stale or never seen",
        sum(dims["connectivity"].get(k, 0) for k in ("offline", "stale", "never_seen")),
    )
    add(
        "Health",
        "System disk critical",
        dims["disk"].get("critical", 0),
        notes=f"{dims['disk'].get('warning', 0)} more at warning level",
    )
    add(
        "Health",
        "Antivirus disabled or outdated",
        sum(dims["antivirus"].get(k, 0) for k in ("disabled", "enabled_outdated")),
    )
    add("Health", "Firewall disabled", dims["firewall"].get("disabled", 0))

    os = patching.summary(customer.id)
    reporting = os["devices_reporting_updates"]
    add(
        "Patching",
        "Devices with available Critical OS updates",
        os["devices_by_severity"].get("Critical", 0) if reporting else None,
        prev["os_updates"]["devices_with_critical"] if prev else None,
        f"of {reporting} devices reporting updates; {os['devices_total'] - reporting} without update data",
    )
    tp = thirdparty.summary(customer.id)["totals"]
    add("Patching", "Outdated third-party installations", tp["outdated"])
    add(
        "Patching",
        "Outdated with no rule in patch policy or no policy",
        tp["outdated_not_covered"] + tp["outdated_no_policy"],
        notes="Policy configuration only; deployment is not reported by VSA X",
    )

    sw = software.summary(customer.id)
    add(
        "Software",
        "Devices with outdated catalogued software",
        sw["unique_assets_with_outdated"],
        prev["software"]["devices_with_outdated"] if prev and prev["software"] else None,
    )
    add(
        "Software",
        "Version compliance %",
        sw["version_compliance_pct"],
        notes=f"{sw['comparable_installations']} of {sw['eligible_installations']} installations comparable",
    )

    lc = lifecycle.summary(customer.id)
    add(
        "Lifecycle",
        "Devices on an end-of-support OS",
        lc["os"]["totals"].get("end_of_support", 0),
        notes=f"{lc['os']['totals'].get('ending_soon', 0)} ending within {lc['ending_soon_days']} days; "
        f"{lc['os']['totals'].get('unknown', 0)} unknown",
    )
    add("Lifecycle", "Devices with end-of-support software", lc["software"]["devices_with_end_of_support"])

    baselines = list(ComplianceBaseline.objects.filter(customer=customer, enabled=True).prefetch_related("rules"))
    if baselines:
        facts = engine.load_facts(customer.id)
        for b in baselines:
            r = engine.evaluate(b, facts)
            add(
                "Compliance",
                f"{b.name}: score %",
                r["score_pct"],
                notes=f"{r['totals']['pass']} compliant, {r['totals']['fail']} not compliant, "
                f"{r['totals']['unknown']} unknown",
            )
    else:
        add("Compliance", "Baselines", 0, notes="No compliance baseline defined")

    net = subnets.summary(subnets.collect(customer.id))
    add(
        "Network",
        "Subnets not in an approved subnet",
        net["by_status"]["unassigned"],
        notes=f"of {net['subnets']} observed",
    )
    add("Network", "Devices outside their approved subnet scope", net["devices_outside_expected"])
    return out
