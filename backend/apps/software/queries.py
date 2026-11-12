"""Customer-keyed read models for software compliance (RPT-02/03/05). Snapshot-safe: current generation,
current evaluation, still-approved mapping. Definitions follow docs/REPORTING.md §2."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from django.db.models import Count, Q, QuerySet

from apps.inventory.queries import current_generations

from .comparator import ALGORITHM_VERSION
from .models import ComplianceEvaluation, ComplianceResult

STATES = ["current", "outdated", "newer", "unknown", "unsupported", "excluded"]


def current_evaluations(customer_id: Any) -> QuerySet[ComplianceEvaluation]:
    return ComplianceEvaluation.objects.filter(
        customer_id=customer_id, is_current=True, generation__in=current_generations(customer_id)
    )


def current_results(customer_id: Any) -> QuerySet[ComplianceResult]:
    return ComplianceResult.objects.filter(
        customer_id=customer_id, evaluation__in=current_evaluations(customer_id)
    ).select_related("installation", "product", "catalog_revision", "exception", "asset")


def installation_rows(customer_id: Any, *, asset_id: Any = None, qs: QuerySet[ComplianceResult] | None = None) -> list:
    results = qs if qs is not None else current_results(customer_id)
    if asset_id is not None:
        results = results.filter(asset_id=asset_id)
    return [result_row(r) for r in results.order_by("installation__raw_name", "id")[:2000]]


def result_row(r: ComplianceResult) -> dict[str, Any]:
    rev = r.catalog_revision
    return {
        "id": str(r.id),
        "asset_id": str(r.asset_id),
        "name": r.installation.raw_name,
        "publisher": r.installation.raw_publisher,
        "installed_version": r.installation.raw_version,
        "product": str(r.product) if r.product else None,
        "product_id": str(r.product_id) if r.product_id else None,
        "channel": r.product.channel if r.product else None,
        "state": r.state,
        "reason_code": r.reason_code,
        "reference_version": rev.reference_version if rev else None,
        "catalog_revision_id": str(rev.id) if rev else None,
        "catalog_source_url": rev.vendor_url if rev else None,
        "catalog_source_checked_at": rev.source_checked_at if rev else None,
        "exception_id": str(r.exception_id) if r.exception_id else None,
    }


def summary(customer_id: Any) -> dict[str, Any]:
    evaluations = list(current_evaluations(customer_id).select_related("generation"))
    results = current_results(customer_id)
    totals = {s: 0 for s in STATES}
    for row in results.values("state").annotate(n=Count("id")):
        totals[row["state"]] = row["n"]
    eligible = sum(totals.values())
    comparable = totals["current"] + totals["outdated"] + totals["newer"]
    compliance_den = totals["current"] + totals["outdated"]
    per_product: dict[str, dict[str, Any]] = {}
    for row in (
        results.exclude(product__isnull=True)
        .values("product_id", "product__vendor", "product__product", "product__channel", "product__edition", "state")
        .annotate(n=Count("id"), assets=Count("asset_id", distinct=True))
    ):
        key = str(row["product_id"])
        entry = per_product.setdefault(
            key,
            {
                "product_id": key,
                "label": " ".join(
                    x for x in (row["product__vendor"], row["product__product"], row["product__edition"]) if x
                ),
                "channel": row["product__channel"],
                "states": {s: 0 for s in STATES},
                "installations": 0,
            },
        )
        entry["states"][row["state"]] += row["n"]
        entry["installations"] += row["n"]
    for key, n in (
        results.exclude(product__isnull=True).values_list("product_id").annotate(a=Count("asset_id", distinct=True))
    ):
        per_product[str(key)]["unique_assets"] = n
    versions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in (
        results.exclude(product__isnull=True)
        .values("product_id", "installation__raw_version", "state")
        .annotate(n=Count("id"), assets=Count("asset_id", distinct=True))
        .order_by("product_id", "-n")
    ):
        versions[str(row["product_id"])].append(
            {
                "version": row["installation__raw_version"],
                "state": row["state"],
                "installations": row["n"],
                "unique_assets": row["assets"],
            }
        )
    for key, entry in per_product.items():
        entry["versions"] = versions.get(key, [])[:50]
    top_unsupported = list(
        results.filter(state="unsupported")
        .values("installation__raw_name", "installation__raw_publisher")
        .annotate(n=Count("id"), assets=Count("asset_id", distinct=True))
        .order_by("-n")[:25]
    )
    return {
        "as_of": [e.generation.published_at for e in evaluations],
        "generation_ids": [str(e.generation_id) for e in evaluations],
        "evaluation_ids": [str(e.id) for e in evaluations],
        "catalog_revision_ids": sorted({rid for e in evaluations for rid in e.revision_ids}),
        "algorithm_version": ALGORITHM_VERSION,
        "data_basis": sorted({e.generation.data_basis for e in evaluations}),
        "totals": totals,
        "eligible_installations": eligible,
        "comparable_installations": comparable,
        "comparable_coverage_pct": round(100 * comparable / eligible, 1) if eligible else None,
        "version_compliance_pct": round(100 * totals["current"] / compliance_den, 1) if compliance_den else None,
        "unique_assets_with_outdated": results.filter(state="outdated").values("asset_id").distinct().count(),
        "unique_assets_evaluated": results.values("asset_id").distinct().count(),
        "products": sorted(per_product.values(), key=lambda p: -p["installations"]),
        "top_unsupported": [
            {
                "name": r["installation__raw_name"],
                "publisher": r["installation__raw_publisher"],
                "installations": r["n"],
                "unique_assets": r["assets"],
            }
            for r in top_unsupported
        ],
        "disclaimer": (
            "Version comparison against a reviewed reference catalog only. Not evidence of missing third-party "
            "patches or vulnerabilities."
        ),
    }


def filtered_results(customer_id: Any, params: Any) -> QuerySet[ComplianceResult]:
    qs = current_results(customer_id)
    state = params.get("state")
    if state in STATES:
        qs = qs.filter(state=state)
    product = (params.get("product") or "").strip()
    if product:
        pid = _uuid_or_none(product)
        qs = qs.filter(product_id=pid) if pid else qs.none()
    search = (params.get("search") or "").strip()[:100]
    if search:
        qs = qs.filter(Q(installation__raw_name__icontains=search) | Q(installation__raw_publisher__icontains=search))
    asset = (params.get("asset") or "").strip()
    if asset:
        aid = _uuid_or_none(asset)
        qs = qs.filter(asset_id=aid) if aid else qs.none()
    return qs


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
