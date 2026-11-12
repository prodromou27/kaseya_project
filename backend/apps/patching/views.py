from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.customers.views import CustomerScopedMixin

from . import queries
from .models import DeviceOsUpdate, PatchObservation


class DeviceOsUpdateSerializer(serializers.ModelSerializer):
    asset_id = serializers.UUIDField()
    hostname = serializers.CharField(source="patch_observation.observation.hostname")
    kb_article = serializers.CharField(source="os_update.kb_article")
    title = serializers.CharField(source="os_update.title")
    update_id = serializers.CharField(source="os_update.update_id")
    revision_number = serializers.IntegerField(source="os_update.revision_number")
    release_date = serializers.CharField(source="os_update.release_date")
    installed_status = serializers.CharField(source="patch_observation.installed_status")
    installed_collected_at = serializers.DateTimeField(source="patch_observation.installed_collected_at")

    class Meta:
        model = DeviceOsUpdate
        fields = [
            "id",
            "asset_id",
            "hostname",
            "state",
            "kb_article",
            "title",
            "update_id",
            "revision_number",
            "severity",
            "category",
            "cvss_score",
            "cve_codes",
            "release_date",
            "installed_at_raw",
            "installed_by_agent",
            "installed_status",
            "installed_collected_at",
        ]


class DevicePatchStatusSerializer(serializers.ModelSerializer):
    asset_id = serializers.UUIDField()
    hostname = serializers.CharField(source="observation.hostname")
    device_type = serializers.CharField(source="observation.device_type")
    os_name = serializers.CharField(source="observation.os_name")
    last_seen_online = serializers.DateTimeField(source="observation.last_seen_online")

    class Meta:
        model = PatchObservation
        fields = [
            "asset_id",
            "hostname",
            "device_type",
            "os_name",
            "last_seen_online",
            "update_counts",
            "available_status",
            "available_count",
            "installed_status",
            "installed_count",
            "installed_collected_at",
            "collected_at",
        ]


class CustomerOsUpdateViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """``/customers/{id}/os-updates/`` — device-by-update rows from the current published generation."""

    customer_capability = Cap.CUSTOMER_READ
    serializer_class = DeviceOsUpdateSerializer

    def get_queryset(self) -> QuerySet[DeviceOsUpdate]:
        if getattr(self, "swagger_fake_view", False):
            return DeviceOsUpdate.objects.none()
        return queries.filtered_device_updates(self.get_customer().id, self.request.query_params).order_by(
            "-os_update__kb_article", "patch_observation__observation__hostname", "id"
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(queries.summary(self.get_customer().id))

    @extend_schema(responses={200: DevicePatchStatusSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def devices(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        qs = queries.filtered_devices(self.get_customer().id, request.query_params).order_by(
            "observation__hostname", "asset_id"
        )
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(DevicePatchStatusSerializer(page, many=True).data)
