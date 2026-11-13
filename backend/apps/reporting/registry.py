"""Report type registry (templates). Report types are code, never user-supplied templates or queries.

Snapshot reports ``pin`` the exact dataset generations / compliance evaluations once; the provenance block and the
rows are both produced from those pinned IDs, so a concurrent publish can never mix snapshots. A regenerated run is
pinned to the *original* IDs (P2-06), which makes historical reports reproducible.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.roles import Cap

ALL_FORMATS = ("csv", "xlsx", "pdf")


@dataclass(frozen=True)
class ReportType:
    key: str
    title: str
    formats: tuple[str, ...]
    # Capabilities required on the report's customer to request, view *and* download it.
    required_capabilities: frozenset[str]
    filter_serializer: type[serializers.Serializer]
    columns: tuple[str, ...]
    rows: Callable[[Any, dict[str, Any], dict[str, Any]], Iterator[list[Any]]]
    data_basis: str = "portal_internal"
    # pin(customer, pinned_or_None) -> {"generation_ids", "evaluation_ids", "data_basis", "provenance"}
    pin: Callable[[Any, dict[str, Any] | None], dict[str, Any]] | None = None
    limitations: str = ""
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ScopedAssetFilterMixin:
    """Any ``asset`` filter must reference an asset of the report's customer (cross-tenant filters denied)."""

    def validate_for_customer(self, customer: Any, data: dict[str, Any]) -> None:
        from apps.inventory.models import Asset

        asset = data.get("asset")
        if asset is not None and not Asset.objects.filter(pk=asset, customer=customer).exists():
            raise serializers.ValidationError({"asset": "Asset not found for this customer."})


# ---------------------------------------------------------------------------------------------- audit


class AuditLogFilters(serializers.Serializer):
    action_prefix = serializers.CharField(required=False, allow_blank=True, max_length=64)
    outcome = serializers.ChoiceField(choices=["success", "denied", "failure"], required=False)
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)


def _audit_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    from apps.audit.models import AuditEvent

    qs = AuditEvent.objects.filter(customer=customer).order_by("created_at", "id")
    if filters.get("action_prefix"):
        qs = qs.filter(action__startswith=filters["action_prefix"])
    if filters.get("outcome"):
        qs = qs.filter(outcome=filters["outcome"])
    if filters.get("since"):
        qs = qs.filter(created_at__gte=filters["since"])
    if filters.get("until"):
        qs = qs.filter(created_at__lt=filters["until"])
    for e in qs.iterator(chunk_size=2000):
        yield [e.created_at.isoformat(), e.action, e.outcome, e.actor_label, e.target_type, e.target_id, e.request_id]


# ---------------------------------------------------------------------------------------------- pinning


def _pin_generations(customer: Any, pinned: dict[str, Any] | None) -> dict[str, Any]:
    from apps.integrations.models import DatasetGeneration
    from apps.inventory.queries import current_generations

    if pinned is not None:
        # Re-pin to the original snapshot. IDs are constrained to this customer: a forged pin can't cross tenants.
        gens = list(
            DatasetGeneration.objects.filter(
                customer=customer, id__in=pinned.get("generations", []), state__in=["published", "superseded"]
            ).select_related("integration_instance")
        )
    else:
        gens = list(current_generations(customer.id).select_related("integration_instance"))
    datasets = "; ".join(f"VSA assets generation {g.id} ({g.integration_instance.name})" for g in gens)
    return {
        "generation_ids": [str(g.id) for g in gens],
        "evaluation_ids": [],
        "data_basis": ",".join(sorted({g.data_basis for g in gens})) or "none",
        "provenance": {
            "Datasets": datasets or "NA",
            "Source last successful sync": "; ".join(g.published_at.isoformat() for g in gens) or "never",
            "Applied catalog revision": "NA",
        },
    }


def _pin_software(customer: Any, pinned: dict[str, Any] | None) -> dict[str, Any]:
    from apps.software.comparator import ALGORITHM_VERSION
    from apps.software.models import ComplianceEvaluation
    from apps.software.queries import current_evaluations

    pins = _pin_generations(customer, pinned)
    if pinned is not None:
        evals = list(ComplianceEvaluation.objects.filter(customer=customer, id__in=pinned.get("evaluations", [])))
    else:
        evals = list(current_evaluations(customer.id))
    pins["evaluation_ids"] = [str(e.id) for e in evals]
    revision_ids = sorted({r for e in evals for r in e.revision_ids})
    algos = sorted({e.algorithm_version for e in evals}) or [ALGORITHM_VERSION]
    applied = f"{len(revision_ids)} revision(s): {', '.join(revision_ids)}" if revision_ids else "none applied"
    pins["provenance"]["Applied catalog revision"] = f"{applied}; comparator {', '.join(algos)}"
    totals: dict[str, int] = {}
    for e in evals:
        for k, v in e.summary.items():
            totals[k] = totals.get(k, 0) + v
    pins["provenance"]["Records unknown/unsupported/excluded"] = (
        f"unknown={totals.get('unknown', 0)}; unsupported={totals.get('unsupported', 0)}; "
        f"excluded={totals.get('excluded', 0)}"
    )
    return pins


def _pin_os_updates(customer: Any, pinned: dict[str, Any] | None) -> dict[str, Any]:
    from apps.patching.models import PatchObservation

    pins = _pin_generations(customer, pinned)
    counts = dict(
        PatchObservation.objects.filter(customer=customer, generation_id__in=pins["generation_ids"])
        .values_list("available_status")
        .annotate(n=Count("id"))
    )
    pins["provenance"]["Devices by AvailableUpdates status"] = (
        "; ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no devices"
    )
    return pins


# ---------------------------------------------------------------------------------------------- RPT-01


class AssetFilters(serializers.Serializer):
    group = serializers.CharField(required=False, allow_blank=True, max_length=255)
    os = serializers.CharField(required=False, allow_blank=True, max_length=255)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)


def _observations(customer: Any, pins: dict[str, Any]) -> Any:
    from apps.inventory.models import AssetObservation

    return AssetObservation.objects.filter(customer=customer, generation_id__in=pins["generation_ids"]).select_related(
        "asset", "generation"
    )


def _asset_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    qs = _observations(customer, pins)
    if filters.get("group"):
        qs = qs.filter(group_name=filters["group"])
    if filters.get("os"):
        qs = qs.filter(os_name=filters["os"])
    if filters.get("search"):
        qs = qs.filter(Q(hostname__icontains=filters["search"]) | Q(serial_number__icontains=filters["search"]))
    for o in qs.order_by("hostname", "asset_id").iterator(chunk_size=2000):
        yield [
            o.asset.external_id,
            o.hostname,
            o.device_type,
            o.group_name,
            o.site_external_id,
            o.os_name,
            o.os_version,
            o.client_version,
            o.last_seen_online.isoformat() if o.last_seen_online else "unknown",
            o.serial_number,
            o.software_status,
            o.generation.published_at.isoformat(),
            str(o.generation_id),
        ]


# ---------------------------------------------------------------------------------------------- RPT-03 / RPT-05


class SoftwareFilters(ScopedAssetFilterMixin, serializers.Serializer):
    state = serializers.ChoiceField(
        choices=["current", "outdated", "newer", "unknown", "unsupported", "excluded"], required=False
    )
    product = serializers.UUIDField(required=False)
    asset = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)


def _results(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Any:
    from apps.software.models import ComplianceResult

    qs = ComplianceResult.objects.filter(customer=customer, evaluation_id__in=pins["evaluation_ids"])
    if filters.get("state"):
        qs = qs.filter(state=filters["state"])
    if filters.get("product"):
        qs = qs.filter(product_id=filters["product"])
    if filters.get("asset"):
        qs = qs.filter(asset_id=filters["asset"])
    if filters.get("search"):
        term = filters["search"]
        qs = qs.filter(Q(installation__raw_name__icontains=term) | Q(installation__raw_publisher__icontains=term))
    return qs


def _software_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    qs = _results(customer, filters, pins).select_related(
        "installation", "installation__observation", "asset", "product", "catalog_revision"
    )
    ordering = ("installation__observation__hostname", "installation__raw_name", "id")
    for r in qs.order_by(*ordering).iterator(chunk_size=2000):
        rev = r.catalog_revision
        yield [
            r.asset.external_id,
            r.installation.observation.hostname,
            r.installation.raw_name,
            r.installation.raw_publisher,
            r.installation.raw_version,
            str(r.product) if r.product else "",
            r.product.channel if r.product else "",
            rev.reference_version if rev else "",
            r.state,
            r.reason_code,
            str(rev.id) if rev else "",
            rev.vendor_url if rev else "",
        ]


class DistributionFilters(serializers.Serializer):
    product = serializers.UUIDField(required=False)


def _distribution_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    qs = _results(customer, filters, pins).exclude(product__isnull=True)
    rows = (
        qs.values("product__vendor", "product__product", "product__channel", "installation__raw_version", "state")
        .annotate(n=Count("id"), assets=Count("asset_id", distinct=True))
        .order_by("product__vendor", "product__product", "product__channel", "-n", "installation__raw_version")
    )
    for r in rows:
        yield [
            f"{r['product__vendor']} {r['product__product']}",
            r["product__channel"],
            r["installation__raw_version"] or "(blank)",
            r["state"],
            r["n"],
            r["assets"],
        ]


SOFTWARE_LIMITATIONS = (
    "Version comparison against a reviewed reference catalog only; NOT evidence of missing third-party patches or "
    "vulnerabilities. VSA X InstalledSoftware does not report architecture or channel; those come from catalog aliases."
)


# ---------------------------------------------------------------------------------------------- RPT-04


class OsUpdateFilters(ScopedAssetFilterMixin, serializers.Serializer):
    state = serializers.ChoiceField(choices=["available", "installed"], required=False)
    severity = serializers.CharField(required=False, allow_blank=True, max_length=32)
    kb = serializers.RegexField(r"^(?:KB)?[0-9]{4,10}$", required=False, max_length=12)
    asset = serializers.UUIDField(required=False)


def _os_update_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    from apps.patching.models import DeviceOsUpdate

    qs = DeviceOsUpdate.objects.filter(customer=customer, generation_id__in=pins["generation_ids"]).select_related(
        "os_update", "asset", "patch_observation", "patch_observation__observation", "generation"
    )
    if filters.get("state"):
        qs = qs.filter(state=filters["state"])
    if filters.get("severity"):
        qs = qs.filter(severity__iexact=filters["severity"])
    if filters.get("kb"):
        qs = qs.filter(os_update__kb_article=filters["kb"].upper().removeprefix("KB"))
    if filters.get("asset"):
        qs = qs.filter(asset_id=filters["asset"])
    for d in qs.order_by("patch_observation__observation__hostname", "state", "os_update__kb_article", "id").iterator(
        chunk_size=2000
    ):
        po = d.patch_observation
        yield [
            d.asset.external_id,
            po.observation.hostname,
            d.state,
            f"KB{d.os_update.kb_article}" if d.os_update.kb_article else "",
            d.os_update.title,
            d.severity,
            d.category,
            "" if d.cvss_score is None else str(d.cvss_score),
            d.os_update.release_date,
            d.installed_at_raw,
            po.installed_status if d.state == "installed" else po.available_status,
            po.installed_collected_at.isoformat() if (d.state == "installed" and po.installed_collected_at) else "",
            d.generation.published_at.isoformat(),
        ]


# ---------------------------------------------------------------------------------------------- RPT-06


class StaleFilters(serializers.Serializer):
    stale_days = serializers.IntegerField(min_value=1, max_value=365, default=7)
    group = serializers.CharField(required=False, allow_blank=True, max_length=255)
    only_stale = serializers.BooleanField(default=True)


def _stale_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    now = timezone.now()
    cutoff = now - timedelta(days=int(filters.get("stale_days", 7)))
    qs = _observations(customer, pins)
    if filters.get("group"):
        qs = qs.filter(group_name=filters["group"])
    if filters.get("only_stale", True):
        qs = qs.filter(Q(last_seen_online__lt=cutoff) | Q(last_seen_online__isnull=True))
    for o in qs.order_by("last_seen_online", "hostname").iterator(chunk_size=2000):
        if o.last_seen_online is None:
            state, age = "never_seen_or_unreported", ""
        else:
            age = f"{(now - o.last_seen_online).total_seconds() / 86400:.1f}"
            state = "stale" if o.last_seen_online < cutoff else "recently_seen"
        yield [
            o.asset.external_id,
            o.hostname,
            o.group_name,
            o.site_external_id,
            o.last_seen_online.isoformat() if o.last_seen_online else "unknown",
            age,
            state,
            o.generation.published_at.isoformat(),
        ]


# ---------------------------------------------------------------------------------------------- R08 (VSA3-04)


class PolicyFilters(serializers.Serializer):
    patch_state = serializers.ChoiceField(
        choices=["assigned", "explicit_none", "not_reported", "unknown"], required=False
    )
    drift = serializers.ChoiceField(
        choices=["no_baseline", "unknown", "matches", "different_policy", "missing_policy", "unexpected_policy"],
        required=False,
    )


def _policy_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    from apps.patching.models import AppliedPolicyObservation
    from apps.patching.policies import approved_baselines, baseline_for, drift

    pol = {
        p.observation_id: p
        for p in AppliedPolicyObservation.objects.filter(customer=customer, generation_id__in=pins["generation_ids"])
    }
    baselines = approved_baselines(customer.id)
    for o in _observations(customer, pins).order_by("hostname", "asset_id").iterator(chunk_size=2000):
        p = pol.get(o.pk)
        state = p.patch_state if p else "unknown"
        base = baseline_for(baselines, o.organization_external_id, o.site_external_id, o.group_external_id)
        d = drift(base, state, p.patch_policy_id if p else "")
        if filters.get("patch_state") and state != filters["patch_state"]:
            continue
        if filters.get("drift") and d != filters["drift"]:
            continue
        yield [
            o.asset.external_id,
            o.hostname,
            o.site_external_id,
            o.group_external_id,
            state,
            p.patch_policy_id if p else "",
            p.patch_policy_name if p else "",
            p.status if p else "not_collected",
            p.collected_at.isoformat() if p and p.collected_at else "",
            "" if base is None else f"{base.scope_type}:{base.scope_external_id}",
            "" if base is None else ("no policy" if base.expect_no_policy else base.expected_policy_id),
            d,
            o.generation.published_at.isoformat(),
        ]


# ---------------------------------------------------------------------------------------------- R09/R13/R14 (VSA4)


class HealthFilters(serializers.Serializer):
    group_id = serializers.RegexField(r"^[0-9]{1,18}$", required=False)


def _health_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> list[dict[str, Any]]:
    from apps.inventory.health import device_rows

    rows = device_rows(customer.id, generation_ids=pins["generation_ids"])
    if filters.get("group_id"):
        rows = [r for r in rows if r["group_external_id"] == filters["group_id"]]
    return rows


def _agent_health_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    for r in _health_rows(customer, filters, pins):
        yield [
            r["hostname"],
            r["site_name"] or r["site_external_id"],
            r["group_name"] or r["group_external_id"],
            r["last_seen_online"] or "unknown",
            "" if r["days_since_seen"] is None else r["days_since_seen"],
            r["connectivity"],
            r["agent_installed"],
            r["client_version"],
            r["agent_version"],
            r["patch_policy"],
            r["snapshot_at"],
        ]


def _capacity_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    for r in _health_rows(customer, filters, pins):
        h = r["hardware"]
        yield [
            r["hostname"],
            r["group_name"] or r["group_external_id"],
            r["disk"],
            "" if r["worst_disk_free_pct"] is None else r["worst_disk_free_pct"],
            h["cpu"],
            h["cores"],
            h["logical_processors"],
            h["memory_total_raw"],
            r["snapshot_at"],
        ]


def _security_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    def tri(v: Any) -> str:
        return "unknown" if v is None else str(v).lower()

    for r in _health_rows(customer, filters, pins):
        a = r["reported_aggregates"]
        yield [
            r["hostname"],
            r["group_name"] or r["group_external_id"],
            r["antivirus"],
            r["firewall"],
            tri(a["AntivirusEnabled"]),
            tri(a["AntivirusUpToDate"]),
            tri(a["FirewallEnabled"]),
            tri(a["UacEnabled"]),
            r["snapshot_at"],
        ]


def _change_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    """R16: pinned generation vs the complete snapshot immediately before it (same instance)."""
    from apps.inventory import changes

    for gen_id in pins["generation_ids"]:
        try:
            frm, to = changes.resolve_pair(customer.id, None, gen_id)
        except changes.NotComparable:
            continue
        d = changes.diff(customer.id, frm, to)
        start = frm.published_at.isoformat() if frm.published_at else "?"
        end = to.published_at.isoformat() if to.published_at else "?"
        window = f"{start} .. {end}"
        for dev in d["devices"]:
            for c in dev["changes"]:
                if filters.get("kind") and c["kind"] != filters["kind"]:
                    continue
                detail = (
                    f"{c.get('from', '')} -> {c.get('to', '')}"
                    if "from" in c
                    else "; ".join(
                        p
                        for p in (
                            f"added: {', '.join(c.get('added', []))}" if c.get("added") else "",
                            f"removed: {', '.join(c.get('removed', []))}" if c.get("removed") else "",
                        )
                        if p
                    )
                )
                yield [
                    dev["external_id"],
                    dev["hostname"],
                    dev["group_external_id"],
                    c["kind"],
                    detail,
                    window,
                    str(frm.pk),
                    str(to.pk),
                ]


class NotificationFilters(serializers.Serializer):
    priority = serializers.CharField(required=False, allow_blank=True, max_length=32)


def _notification_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    from apps.inventory.models import DeviceNotification

    qs = DeviceNotification.objects.filter(customer=customer, generation_id__in=pins["generation_ids"]).select_related(
        "asset", "fetch__observation", "generation"
    )
    if filters.get("priority"):
        qs = qs.filter(priority=filters["priority"].lower())
    for n in qs.order_by("-occurred_at", "id").iterator(chunk_size=2000):
        yield [
            n.asset.external_id,
            n.fetch.observation.hostname,
            n.priority,
            n.occurred_at.isoformat() if n.occurred_at else (n.occurred_raw or "unknown"),
            n.message,
            n.redactions,
            n.generation.published_at.isoformat(),
        ]


class ChangeFilters(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=[
            "device_added",
            "device_removed",
            "hostname",
            "group",
            "site",
            "os",
            "agent_version",
            "agent_installed",
            "ip_addresses",
            "software",
        ],
        required=False,
    )


# ---------------------------------------------------------------------------------------------- R17 lifecycle


class LifecycleFilters(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["os", "software"], required=False)
    status = serializers.ChoiceField(choices=["end_of_support", "ending_soon", "supported", "unknown"], required=False)


def _pin_lifecycle(customer: Any, pinned: dict[str, Any] | None) -> dict[str, Any]:
    """Snapshot + software evaluation + the evaluation date + the exact approved lifecycle entries used."""
    from django.utils import timezone

    from apps.software import lifecycle

    pins = _pin_software(customer, pinned)
    if pinned is not None and "lifecycle_on" in pinned:
        on, entry_ids = pinned["lifecycle_on"], [str(i) for i in pinned.get("lifecycle_entries", [])]
    else:
        on = timezone.localdate().isoformat()
        os_entries, by_product = lifecycle.approved_entries()
        entry_ids = sorted({str(e.id) for e in os_entries} | {str(e.id) for es in by_product.values() for e in es})
    pins["extra_pins"] = {"lifecycle_on": on, "lifecycle_entries": entry_ids}
    pins["provenance"]["Lifecycle"] = (
        f"evaluated on {on}; {len(entry_ids)} approved lifecycle entr{'y' if len(entry_ids) == 1 else 'ies'}; "
        f"algorithm {lifecycle.ALGORITHM_VERSION}"
    )
    return pins


def _lifecycle_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    import datetime as dt

    from apps.software import lifecycle

    on = dt.date.fromisoformat(pins["extra_pins"]["lifecycle_on"])
    entry_ids = pins["extra_pins"]["lifecycle_entries"]
    kinds = [filters["kind"]] if filters.get("kind") else ["os", "software"]
    for kind in kinds:
        if kind == "os":
            rows = lifecycle.os_rows(customer.id, on, generation_ids=pins["generation_ids"], entry_ids=entry_ids)
        else:
            rows = lifecycle.software_rows(
                customer.id,
                on,
                generation_ids=pins["generation_ids"],
                evaluation_ids=pins["evaluation_ids"],
                entry_ids=entry_ids,
            )
        for r in rows:
            if filters.get("status") and r["status"] != filters["status"]:
                continue
            e = r["entry"] or {}
            yield [
                kind,
                r["hostname"],
                r.get("os_name") or r.get("name") or "",
                r.get("os_version") or r.get("installed_version") or "",
                r["status"],
                r["reason"],
                e.get("label", ""),
                e.get("end_of_support") or "",
                e.get("extended_until") or "",
                e.get("source_url", ""),
                e.get("source_checked_at") or "",
                on.isoformat(),
            ]


SNAPSHOT_NOTE = (
    "Inventory snapshot at the generation publish time, not live monitoring telemetry. 'unknown', 'not_reported' "
    "and 'not_collected' are neither healthy nor unhealthy. Thresholds are those approved at generation time "
    "(or documented defaults)."
)

# ---------------------------------------------------------------------------------------------- registry

SNAPSHOT_CAPS = frozenset({Cap.CUSTOMER_EXPORT, Cap.CUSTOMER_READ})

REPORT_TYPES: dict[str, ReportType] = {
    "customer_audit_log": ReportType(
        key="customer_audit_log",
        title="Customer audit log",
        description="Portal audit events for this customer.",
        formats=ALL_FORMATS,
        required_capabilities=frozenset({Cap.CUSTOMER_EXPORT, Cap.CUSTOMER_AUDIT_READ}),
        filter_serializer=AuditLogFilters,
        columns=("created_at_utc", "action", "outcome", "actor", "target_type", "target_id", "request_id"),
        rows=_audit_rows,
    ),
    "asset_inventory": ReportType(
        key="asset_inventory",
        title="Asset inventory (RPT-01)",
        description="Devices in the published inventory snapshot.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=AssetFilters,
        columns=(
            "device_id",
            "hostname",
            "type",
            "group",
            "site_id",
            "os",
            "os_version",
            "agent_version",
            "last_seen_online_utc",
            "serial_number",
            "software_inventory",
            "source_as_of_utc",
            "generation_id",
        ),
        rows=_asset_rows,
        pin=_pin_generations,
        limitations="Approved source mappings only; quarantined records are excluded (see sync health).",
    ),
    "software_compliance": ReportType(
        key="software_compliance",
        title="Software version compliance (RPT-03)",
        description="Each installation with its reference version and classification.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=SoftwareFilters,
        columns=(
            "device_id",
            "hostname",
            "installed_name",
            "publisher",
            "installed_version",
            "catalog_product",
            "channel",
            "reference_version",
            "classification",
            "reason_code",
            "catalog_revision_id",
            "catalog_evidence_url",
        ),
        rows=_software_rows,
        pin=_pin_software,
        limitations=SOFTWARE_LIMITATIONS,
    ),
    "os_updates": ReportType(
        key="os_updates",
        title="Operating system updates (RPT-04)",
        description="Available and installed OS updates as reported by VSA X.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=OsUpdateFilters,
        columns=(
            "device_id",
            "hostname",
            "state",
            "kb",
            "title",
            "severity",
            "category",
            "cvss",
            "release_date",
            "installed_at_as_reported_tz_unspecified",
            "section_status",
            "installed_collected_at_utc",
            "source_as_of_utc",
        ),
        rows=_os_update_rows,
        pin=_pin_os_updates,
        limitations=(
            "OS updates reported by VSA X only; not third-party application patches. Devices whose source returned no "
            "AvailableUpdates section, or non-Windows devices, are listed in the status counts above and are NOT "
            "counted as having zero missing updates. The API documents no scan timestamp; InstalledAt has no timezone."
        ),
    ),
    "software_distribution": ReportType(
        key="software_distribution",
        title="Software version distribution (RPT-05)",
        description="Installations and unique devices per catalogued product version.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=DistributionFilters,
        columns=("product", "channel", "installed_version", "classification", "installations", "unique_devices"),
        rows=_distribution_rows,
        pin=_pin_software,
        limitations=SOFTWARE_LIMITATIONS,
    ),
    "stale_devices": ReportType(
        key="stale_devices",
        title="Offline / stale devices (RPT-06)",
        description="Devices not seen online within the threshold.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=StaleFilters,
        columns=(
            "device_id",
            "hostname",
            "group",
            "site_id",
            "last_seen_online_utc",
            "age_days",
            "state",
            "source_as_of_utc",
        ),
        rows=_stale_rows,
        pin=_pin_generations,
        limitations="Age is computed at generation time from LastSeenOnline; devices without a value are listed "
        "as never_seen_or_unreported, not as online.",
    ),
    "patch_policy_coverage": ReportType(
        key="patch_policy_coverage",
        title="Patch policy coverage and drift (R08)",
        description="Per-device Patch Management assignment, explicit No Policy, unknown, and drift vs approved "
        "expectations.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=PolicyFilters,
        columns=(
            "device_id",
            "hostname",
            "site_id",
            "group_id",
            "patch_state",
            "policy_id",
            "policy_name",
            "collection_status",
            "policy_collected_at_utc",
            "expected_scope",
            "expected_policy",
            "drift",
            "source_as_of_utc",
        ),
        rows=_policy_rows,
        pin=_pin_generations,
        limitations="Assignment is configuration, not deployment: an assigned policy is not evidence that patches "
        "were installed. 'unknown' = not collected; 'not_reported' = no Patch Management entry in the response. "
        "Drift uses the expectations approved at report generation time.",
    ),
    "device_notifications": ReportType(
        key="device_notifications",
        title="Device notifications (R15)",
        description="VSA X device notifications inside the retention window, redacted for credentials and "
        "personal data.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=NotificationFilters,
        columns=(
            "device_id",
            "hostname",
            "priority",
            "occurred_utc",
            "message_redacted",
            "redactions",
            "source_as_of_utc",
        ),
        rows=_notification_rows,
        pin=_pin_generations,
        limitations="Only devices within the per-sync notification budget are collected; a device with no rows may "
        "not have been collected. Messages are redacted (credentials, e-mail addresses, DOMAIN\\user) before storage.",
    ),
    "inventory_changes": ReportType(
        key="inventory_changes",
        title="Inventory changes (R16)",
        description="Devices added/removed and hostname, group, site, OS, agent, IP and software differences "
        "between the pinned snapshot and the complete snapshot before it.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=ChangeFilters,
        columns=(
            "device_id",
            "hostname",
            "group_id",
            "change",
            "detail",
            "observed_between_utc",
            "from_generation",
            "to_generation",
        ),
        rows=_change_rows,
        pin=_pin_generations,
        limitations="Differences observed between two complete snapshots; the time is the snapshot window, not when "
        "the change happened, and no person is attributed. IP/software sections are compared only when collected in "
        "both snapshots.",
    ),
    "agent_health": ReportType(
        key="agent_health",
        title="Agent health (R09)",
        description="Last seen, offline/stale cohort, agent installed, client version vs approved minimum.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=HealthFilters,
        columns=(
            "hostname",
            "site",
            "group",
            "last_seen_online_utc",
            "days_since_seen",
            "connectivity",
            "agent_installed",
            "client_version",
            "agent_version_state",
            "patch_policy",
            "source_as_of_utc",
        ),
        rows=_agent_health_rows,
        pin=_pin_generations,
        limitations=SNAPSHOT_NOTE + " agent_version_state is 'not_evaluated' until a minimum version is approved.",
    ),
    "disk_hardware": ReportType(
        key="disk_hardware",
        title="Disk and hardware capacity (R13)",
        description="Worst system-disk free %, disk state vs thresholds, CPU and memory as reported.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=HealthFilters,
        columns=(
            "hostname",
            "group",
            "disk_state",
            "worst_disk_free_pct",
            "cpu",
            "cores",
            "logical_processors",
            "memory_total_raw",
            "source_as_of_utc",
        ),
        rows=_capacity_rows,
        pin=_pin_generations,
        limitations=SNAPSHOT_NOTE + " MemoryTotal and disk TotalValue units are not documented and are shown raw.",
    ),
    "security_observations": ReportType(
        key="security_observations",
        title="Security observations (R14)",
        description="Antivirus and firewall state from the Security section plus the reported aggregate flags.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=HealthFilters,
        columns=(
            "hostname",
            "group",
            "antivirus_state",
            "firewall_state",
            "reported_AntivirusEnabled",
            "reported_AntivirusUpToDate",
            "reported_FirewallEnabled",
            "reported_UacEnabled",
            "source_as_of_utc",
        ),
        rows=_security_rows,
        pin=_pin_generations,
        limitations=SNAPSHOT_NOTE + " A disabled or unknown state is an observation, not a confirmed incident.",
    ),
    "lifecycle": ReportType(
        key="lifecycle",
        title="OS and software lifecycle (R17)",
        description="Support end dates per device OS and per catalogued software installation, with the cited source.",
        formats=ALL_FORMATS,
        required_capabilities=SNAPSHOT_CAPS,
        filter_serializer=LifecycleFilters,
        columns=(
            "kind",
            "hostname",
            "reported_name",
            "reported_version",
            "lifecycle_status",
            "reason",
            "lifecycle_entry",
            "end_of_support",
            "extended_support_until",
            "source_url",
            "source_checked_at",
            "evaluated_on",
        ),
        rows=_lifecycle_rows,
        pin=_pin_lifecycle,
        limitations=SNAPSHOT_NOTE
        + " Only approved lifecycle entries from official vendor sources classify a row; everything else is unknown."
        + " Lifecycle status is not a patch or vulnerability statement.",
    ),
}


def validate_filters(report_type: ReportType, customer: Any, raw: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted, typed, customer-checked filters → JSON-safe dict. Raises ``ValidationError``."""
    s = report_type.filter_serializer(data=raw or {})
    s.is_valid(raise_exception=True)
    unknown = set(raw or {}) - set(s.fields)
    if unknown:
        raise serializers.ValidationError({"filters": f"Unknown filter keys: {', '.join(sorted(unknown))}"})
    if hasattr(s, "validate_for_customer"):
        s.validate_for_customer(customer, s.validated_data)
    return {
        k: (v.isoformat() if hasattr(v, "isoformat") else (str(v) if hasattr(v, "hex") else v))
        for k, v in s.validated_data.items()
    }
