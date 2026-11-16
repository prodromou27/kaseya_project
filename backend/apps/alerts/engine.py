"""Evaluate watchlists after a sync. Each kind yields the set of keys that currently match (asset IDs, or a
baseline marker); only keys that are *newly* matching raise an alert, summarised in one alert per subscription.
The first evaluation of a subscription only records the starting state, so enabling a watch never floods anyone.
Access is re-checked at evaluation time: a user who lost access to the customer receives nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework import serializers

from .models import Alert, AlertSubscription

logger = logging.getLogger(__name__)
Kind = AlertSubscription.Kind


def clean_params(kind: str, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise serializers.ValidationError({"params": "Parameters must be an object."})

    def number(key: str, low: int, high: int) -> int:
        v = params.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high:
            raise serializers.ValidationError({"params": f"{key} must be a number from {low} to {high}."})
        return int(v)

    if kind == Kind.OFFLINE:
        return {"days": number("days", 1, 365)}
    if kind == Kind.FORBIDDEN_SOFTWARE:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise serializers.ValidationError({"params": "Enter part of the program name (max 120 characters)."})
        return {"name": name.strip()}
    if kind == Kind.COMPLIANCE_BELOW:
        return {"percent": number("percent", 1, 100), "baseline": str(params.get("baseline", ""))[:64]}
    if kind in Kind.values:
        return {}
    raise serializers.ValidationError({"kind": "Unknown alert kind."})


def describe(kind: str, params: dict[str, Any]) -> str:
    if kind == Kind.OFFLINE:
        return f"Device not seen for more than {params['days']} days"
    if kind == Kind.FORBIDDEN_SOFTWARE:
        return f"“{params['name']}” appears on a device"
    if kind == Kind.COMPLIANCE_BELOW:
        return f"Compliance score below {params['percent']}%"
    return Kind(kind).label


def _matches(sub: AlertSubscription, cache: dict[str, Any]) -> tuple[dict[str, str], str]:
    """{key: display text} currently matching, and the portal link for the alert."""
    from apps.inventory.health import device_rows

    customer_id = sub.customer_id
    if "health" not in cache:
        cache["health"] = device_rows(customer_id)
    rows = cache["health"]
    if sub.kind == Kind.NEW_DEVICE:
        return {r["asset_id"]: r["hostname"] for r in rows}, "/assets"
    if sub.kind == Kind.OFFLINE:
        days = sub.params["days"]
        return {r["asset_id"]: r["hostname"] for r in rows if (r["days_since_seen"] or 0) > days}, (
            "/device-health?connectivity=offline,stale,never_seen"
        )
    if sub.kind == Kind.DISK_CRITICAL:
        return {r["asset_id"]: r["hostname"] for r in rows if r["disk"] == "critical"}, "/device-health?disk=critical"
    if sub.kind == Kind.FORBIDDEN_SOFTWARE:
        from apps.inventory.queries import current_generations
        from apps.software.models import SoftwareInstallation

        hosts = {r["asset_id"]: r["hostname"] for r in rows}
        found = SoftwareInstallation.objects.filter(
            customer_id=customer_id,
            generation__in=current_generations(customer_id),
            raw_name__icontains=sub.params["name"],
        ).values_list("asset_id", flat=True)
        return {str(a): hosts.get(str(a), str(a)) for a in found}, "/software?view=programs"
    if sub.kind == Kind.WORKFLOW_FAILED:
        from datetime import timedelta

        from django.utils import timezone

        from apps.automation.models import WorkflowExecution

        hosts = {r["asset_id"]: r["hostname"] for r in rows}
        failed = WorkflowExecution.objects.filter(
            customer_id=customer_id, status="Failed", created_at__gte=timezone.now() - timedelta(days=7)
        ).values_list("external_id", "asset_id", "integration_instance_id")
        return {f"{i}:{x}": hosts.get(str(a), "device") for x, a, i in failed}, "/automation"
    if sub.kind == Kind.COMPLIANCE_BELOW:
        from apps.compliance import engine
        from apps.compliance.models import ComplianceBaseline

        baselines = ComplianceBaseline.objects.filter(customer_id=customer_id, enabled=True).prefetch_related("rules")
        if sub.params.get("baseline"):
            baselines = baselines.filter(pk=sub.params["baseline"])
        if "facts" not in cache:
            cache["facts"] = engine.load_facts(customer_id)
        out = {}
        for b in baselines:
            score = engine.evaluate(b, cache["facts"])["score_pct"]
            if score is not None and score < sub.params["percent"]:
                out[f"baseline:{b.id}"] = f"{b.name} at {score}%"
        return out, "/compliance"
    return {}, "/"


def evaluate_customer(customer_id: Any) -> int:
    """Evaluate every enabled subscription of the customer. Returns the number of alerts created."""
    from apps.accounts import scope
    from apps.accounts.roles import Cap
    from apps.customers.models import Customer

    customer = Customer.objects.filter(pk=customer_id).first()
    if customer is None:
        return 0
    cache: dict[str, Any] = {}
    created = 0
    for sub in AlertSubscription.objects.filter(customer=customer, enabled=True).select_related("user"):
        scope.invalidate_cache(sub.user)
        if not sub.user.is_active or not scope.has_customer_capability(sub.user, customer.id, Cap.CUSTOMER_READ):
            continue
        try:
            current, link = _matches(sub, cache)
        except Exception:  # one broken watch must not stop the others
            logger.exception("alert_evaluation_failed", extra={"subscription_id": str(sub.id)})
            continue
        previous = set(sub.state or [])
        new = [k for k in current if k not in previous]
        if sub.state is not None and new:
            names = sorted(current[k] for k in new)
            shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
            Alert.objects.create(
                user=sub.user,
                customer=customer,
                subscription=sub,
                kind=sub.kind,
                title=f"{customer.code}: {describe(sub.kind, sub.params)} ({len(new)})",
                body=shown,
                link=link,
            )
            created += 1
        sub.state = sorted(current)
        sub.save(update_fields=["state"])
    return created
