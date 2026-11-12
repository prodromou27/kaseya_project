from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.integrations.models import DatasetGeneration

from . import comparator
from .models import (
    CatalogRevision,
    ComplianceEvaluation,
    ComplianceResult,
    ReviewStatus,
    SoftwareAlias,
    SoftwareException,
    SoftwareInstallation,
    SoftwareProduct,
)


def _catalog_state(customer_id: Any, at: Any) -> dict[str, Any]:
    aliases = [
        comparator.AliasRule(str(a.product_id), a.name_pattern, a.publisher_pattern, a.match_type)
        for a in SoftwareAlias.objects.filter(review_status=ReviewStatus.APPROVED, product__active=True)
    ]
    products = {
        str(p.id): comparator.ProductInfo(str(p.id), p.architecture)
        for p in SoftwareProduct.objects.filter(active=True)
    }
    revisions = [
        comparator.RevisionInfo(str(r.id), str(r.product_id), r.reference_version, r.version_scheme, r.effective_at)
        for r in CatalogRevision.objects.filter(state=CatalogRevision.State.PUBLISHED)
    ]
    exceptions = [
        comparator.ExceptionInfo(str(e.id), str(e.product_id), str(e.asset_id) if e.asset_id else None)
        for e in SoftwareException.objects.filter(
            customer_id=customer_id, status=SoftwareException.Status.ACTIVE, expires_at__gt=at
        )
    ]
    fingerprint_src = json.dumps(
        {
            "a": sorted((a.product_id, a.name_pattern, a.publisher_pattern, a.match_type) for a in aliases),
            "p": sorted((p.id, p.architecture) for p in products.values()),
            "r": sorted(r.id for r in revisions),
            "e": sorted(e.id for e in exceptions),
            "alg": comparator.ALGORITHM_VERSION,
        }
    )
    return {
        "aliases": aliases,
        "products": products,
        "revisions": revisions,
        "exceptions": exceptions,
        "fingerprint": hashlib.sha256(fingerprint_src.encode()).hexdigest(),
    }


def evaluate_generation(generation: DatasetGeneration, *, force: bool = False) -> ComplianceEvaluation:
    """Classify every installation of a published generation. Idempotent for an unchanged catalog state."""
    at = timezone.now()
    state = _catalog_state(generation.customer_id, at)
    current = ComplianceEvaluation.objects.filter(generation=generation, is_current=True).first()
    if current and current.catalog_fingerprint == state["fingerprint"] and not force:
        return current

    installations = SoftwareInstallation.objects.filter(generation=generation).only(
        "id", "asset_id", "customer_id", "raw_name", "raw_publisher", "raw_version"
    )
    results: list[ComplianceResult] = []
    counts: Counter[str] = Counter()
    used_revisions: set[str] = set()
    with transaction.atomic():
        evaluation = ComplianceEvaluation.objects.create(
            customer_id=generation.customer_id,
            generation=generation,
            algorithm_version=comparator.ALGORITHM_VERSION,
            catalog_fingerprint=state["fingerprint"],
        )
        for inst in installations.iterator(chunk_size=5000):
            c = comparator.classify(
                name=inst.raw_name,
                publisher=inst.raw_publisher,
                version=inst.raw_version,
                asset_id=str(inst.asset_id),
                aliases=state["aliases"],
                products=state["products"],
                revisions=state["revisions"],
                exceptions=state["exceptions"],
                at=at,
            )
            counts[c.state] += 1
            if c.revision_id:
                used_revisions.add(c.revision_id)
            results.append(
                ComplianceResult(
                    evaluation=evaluation,
                    installation_id=inst.id,
                    customer_id=inst.customer_id,
                    asset_id=inst.asset_id,
                    product_id=c.product_id,
                    catalog_revision_id=c.revision_id,
                    exception_id=c.exception_id,
                    state=c.state,
                    reason_code=c.reason_code,
                )
            )
            if len(results) >= 5000:
                ComplianceResult.objects.bulk_create(results)
                results.clear()
        ComplianceResult.objects.bulk_create(results)
        evaluation.summary = dict(counts)
        evaluation.revision_ids = sorted(used_revisions)
        ComplianceEvaluation.objects.filter(generation=generation, is_current=True).update(is_current=False)
        evaluation.is_current = True
        evaluation.save(update_fields=["summary", "revision_ids", "is_current"])
    return evaluation


def reevaluate_current(customer_id: Any | None = None) -> int:
    """Re-run classification for every current generation (after catalog/exception changes)."""
    qs = DatasetGeneration.objects.filter(is_current=True, dataset="vsa_assets")
    if customer_id is not None:
        qs = qs.filter(customer_id=customer_id)
    count = 0
    for generation in qs:
        evaluate_generation(generation)
        count += 1
    return count


def current_evaluation_filter(prefix: str = "") -> Q:
    """Q for results belonging to the current evaluation of a current, approved-mapping generation."""
    p = prefix
    return Q(
        **{
            f"{p}evaluation__is_current": True,
            f"{p}evaluation__generation__is_current": True,
            f"{p}evaluation__generation__mapping__mapping_status": "approved",
        }
    )
