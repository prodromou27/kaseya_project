"""One inventory filter contract for the portal and pinned report populations.

Callers must supply an already customer-scoped queryset. These filters never widen it.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework import serializers

ORDERING = (
    "hostname",
    "-hostname",
    "last_seen_online",
    "-last_seen_online",
    "group_name",
    "-group_name",
    "os_name",
    "-os_name",
)
EXACT_FIELDS = {
    "group": "group_name",
    "os": "os_name",
    "device_type": "device_type",
    "site": "site_external_id",
    "group_id": "group_external_id",
    "software_status": "software_status",
    "organization": "organization_external_id",
    "instance": "generation__integration_instance_id",
}


class AssetFilters(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    group = serializers.CharField(required=False, allow_blank=True, max_length=255)
    os = serializers.CharField(required=False, allow_blank=True, max_length=255)
    device_type = serializers.CharField(required=False, allow_blank=True, max_length=255)
    site = serializers.CharField(required=False, allow_blank=True, max_length=255)
    group_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    organization = serializers.CharField(required=False, allow_blank=True, max_length=255)
    instance = serializers.UUIDField(required=False)
    software_status = serializers.ChoiceField(choices=["collected", "not_collected"], required=False)
    offline = serializers.BooleanField(required=False)
    offline_days = serializers.IntegerField(required=False, min_value=1, max_value=365)
    ordering = serializers.ChoiceField(choices=ORDERING, required=False)
    asset_ids = serializers.CharField(
        required=False, max_length=19000, help_text="Comma-separated device UUIDs, at most 500."
    )

    def validate_asset_ids(self, value: str) -> str:
        parts = value.split(",")
        if len(parts) > 500:
            raise serializers.ValidationError("Select at most 500 devices.")
        field = serializers.UUIDField()
        return ",".join(dict.fromkeys(str(field.run_validation(part.strip())) for part in parts))

    def validate_for_customer(self, customer: Any, data: dict[str, Any]) -> None:
        from .models import Asset

        if selected := data.get("asset_ids"):
            ids = selected.split(",")
            if Asset.objects.filter(customer=customer, pk__in=ids).count() != len(ids):
                raise serializers.ValidationError({"asset_ids": "A selected device was not found for this customer."})


def filter_inventory(qs: QuerySet, filters: dict[str, Any], *, as_of: datetime | None = None) -> QuerySet:
    if selected := filters.get("asset_ids"):
        qs = qs.filter(asset_id__in=selected.split(","))
    search = filters.get("search", "").strip()
    if search:
        cond = Q(hostname__icontains=search) | Q(serial_number__icontains=search) | Q(asset__external_id=search)
        mac = re.sub(r"[^0-9A-Fa-f]", "", search).upper()
        if len(mac) == 12:
            cond |= Q(adapters__mac=mac)
        with contextlib.suppress(ValueError):
            cond |= Q(adapters__ips__address=ipaddress.ip_address(search.partition("%")[0]).compressed)
        qs = qs.filter(cond).distinct()
    for param, field in EXACT_FIELDS.items():
        if value := filters.get(param):
            qs = qs.filter(**{field: value})
    if "offline" in filters:
        cutoff = (as_of or timezone.now()) - timedelta(days=filters.get("offline_days", 7))
        cond = Q(last_seen_online__lt=cutoff) | Q(last_seen_online__isnull=True)
        qs = qs.filter(cond) if filters["offline"] else qs.exclude(cond)
    return qs.order_by(filters.get("ordering", "hostname"), "asset_id")
