"""Snapshot-safe read helpers. Every query is keyed by an already-authorised customer ID."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from apps.integrations.models import DatasetGeneration

from .models import AssetObservation

DATASET = "vsa_assets"


def current_generations(customer_id: Any) -> QuerySet[DatasetGeneration]:
    """Current published generations whose source mapping is *still* approved (revocation hides data)."""
    return DatasetGeneration.objects.filter(
        customer_id=customer_id, dataset=DATASET, is_current=True, mapping__mapping_status="approved"
    )


def current_observations(customer_id: Any) -> QuerySet[AssetObservation]:
    return AssetObservation.objects.filter(
        customer_id=customer_id,
        generation__in=current_generations(customer_id),
    ).select_related("asset", "generation", "generation__integration_instance")


def stale_cutoff() -> Any:
    return timezone.now() - timedelta(hours=settings.DATA_STALE_AFTER_HOURS)
