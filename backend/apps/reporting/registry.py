"""Report type registry. Report types are code, never user-supplied templates or queries.

Snapshot reports ``pin`` the exact dataset generations / compliance evaluations once; the provenance block and
the rows are both produced from those pinned IDs, so a concurrent publish can never mix two snapshots.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from rest_framework import serializers

from apps.accounts.roles import Cap


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
    # pin(customer) -> {"generation_ids", "evaluation_ids", "data_basis", "provenance"}
    pin: Callable[[Any], dict[str, Any]] | None = None
    limitations: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


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
        yield [
            e.created_at.isoformat(),
            e.action,
            e.outcome,
            e.actor_label,
            e.target_type,
            e.target_id,
            e.request_id,
        ]


# ---------------------------------------------------------------------------------------------- RPT-01


class AssetFilters(serializers.Serializer):
    group = serializers.CharField(required=False, allow_blank=True, max_length=255)
    os = serializers.CharField(required=False, allow_blank=True, max_length=255)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)


def _pin_assets(customer: Any) -> dict[str, Any]:
    from apps.inventory.queries import current_generations

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


def _asset_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    from django.db.models import Q

    from apps.inventory.models import AssetObservation

    qs = AssetObservation.objects.filter(customer=customer, generation_id__in=pins["generation_ids"]).select_related(
        "asset", "generation"
    )
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


# ---------------------------------------------------------------------------------------------- RPT-03


class SoftwareFilters(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=["current", "outdated", "newer", "unknown", "unsupported", "excluded"], required=False
    )
    product = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)


def _pin_software(customer: Any) -> dict[str, Any]:
    from apps.software.comparator import ALGORITHM_VERSION
    from apps.software.queries import current_evaluations

    pins = _pin_assets(customer)
    evals = list(current_evaluations(customer.id))
    pins["evaluation_ids"] = [str(e.id) for e in evals]
    revision_ids = sorted({r for e in evals for r in e.revision_ids})
    if revision_ids:
        applied = f"{len(revision_ids)} revision(s): {', '.join(revision_ids)}; comparator {ALGORITHM_VERSION}"
    else:
        applied = f"none applied; comparator {ALGORITHM_VERSION}"
    pins["provenance"]["Applied catalog revision"] = applied
    totals: dict[str, int] = {}
    for e in evals:
        for k, v in e.summary.items():
            totals[k] = totals.get(k, 0) + v
    pins["provenance"]["Records unknown/unsupported/excluded"] = (
        f"unknown={totals.get('unknown', 0)}; unsupported={totals.get('unsupported', 0)}; "
        f"excluded={totals.get('excluded', 0)}"
    )
    return pins


def _software_rows(customer: Any, filters: dict[str, Any], pins: dict[str, Any]) -> Iterator[list[Any]]:
    from django.db.models import Q

    from apps.software.models import ComplianceResult

    qs = ComplianceResult.objects.filter(customer=customer, evaluation_id__in=pins["evaluation_ids"]).select_related(
        "installation", "installation__observation", "asset", "product", "catalog_revision"
    )
    if filters.get("state"):
        qs = qs.filter(state=filters["state"])
    if filters.get("product"):
        qs = qs.filter(product_id=filters["product"])
    if filters.get("search"):
        term = filters["search"]
        qs = qs.filter(Q(installation__raw_name__icontains=term) | Q(installation__raw_publisher__icontains=term))
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


SOFTWARE_LIMITATIONS = (
    "Version comparison against a reviewed reference catalog only; NOT evidence of missing third-party patches or "
    "vulnerabilities. VSA X InstalledSoftware does not report architecture or channel; those come from catalog aliases."
)


REPORT_TYPES: dict[str, ReportType] = {
    "customer_audit_log": ReportType(
        key="customer_audit_log",
        title="Customer audit log",
        formats=("csv",),
        required_capabilities=frozenset({Cap.CUSTOMER_EXPORT, Cap.CUSTOMER_AUDIT_READ}),
        filter_serializer=AuditLogFilters,
        columns=("created_at_utc", "action", "outcome", "actor", "target_type", "target_id", "request_id"),
        rows=_audit_rows,
    ),
    "asset_inventory": ReportType(
        key="asset_inventory",
        title="Asset inventory (RPT-01)",
        formats=("csv",),
        required_capabilities=frozenset({Cap.CUSTOMER_EXPORT, Cap.CUSTOMER_READ}),
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
        pin=_pin_assets,
        limitations="Approved source mappings only; quarantined records are excluded (see sync health).",
    ),
    "software_compliance": ReportType(
        key="software_compliance",
        title="Software version compliance (RPT-03)",
        formats=("csv",),
        required_capabilities=frozenset({Cap.CUSTOMER_EXPORT, Cap.CUSTOMER_READ}),
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
}
