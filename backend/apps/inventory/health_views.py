"""VSA4-01/02 API: ``/customers/{id}/device-health/`` (read) and ``/customers/{id}/health-thresholds/``.

Thresholds: propose/approve/reject need ``customer.manage_exceptions``; approval must come from a different user
(``CATALOG_REQUIRE_SEPARATE_REVIEWER``). Approval supersedes the previously approved row (history retained).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin
from apps.software.comparator import parse_dotted

from . import health
from .models import HealthThresholds


class CustomerDeviceHealthViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    customer_capability = Cap.CUSTOMER_READ

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(health.summary(self.get_customer().id))

    @extend_schema(
        parameters=[OpenApiParameter(d, str) for d in health.DIMENSIONS]
        + [OpenApiParameter("group_id", str), OpenApiParameter("q", str)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def devices(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        rows = health.filter_rows(health.device_rows(self.get_customer().id), request.query_params)
        page = self.paginate_queryset(rows)  # type: ignore[arg-type]
        return self.get_paginated_response(page)


class HealthThresholdsSerializer(serializers.ModelSerializer):
    proposed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = HealthThresholds
        fields = [
            "id",
            "offline_hours",
            "stale_days",
            "disk_warning_free_pct",
            "disk_critical_free_pct",
            "minimum_agent_version",
            "reason",
            "state",
            "proposed_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = ["id", "state", "proposed_by", "reviewed_by", "reviewed_at", "created_at"]
        extra_kwargs = {
            "offline_hours": {"min_value": 1, "max_value": 24 * 90},
            "stale_days": {"min_value": 1, "max_value": 365},
            "disk_warning_free_pct": {"min_value": 1, "max_value": 100},
            "disk_critical_free_pct": {"min_value": 0, "max_value": 99},
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("disk_critical_free_pct", 5) >= attrs.get("disk_warning_free_pct", 15):
            raise serializers.ValidationError({"disk_critical_free_pct": "Must be below the warning threshold."})
        if attrs.get("stale_days", 7) * 24 <= attrs.get("offline_hours", 24):
            raise serializers.ValidationError({"stale_days": "Stale must be longer than offline."})
        version = attrs.get("minimum_agent_version", "").strip()
        if version and parse_dotted(version) is None:
            raise serializers.ValidationError({"minimum_agent_version": "Use a dotted numeric version, e.g. 5.1.2."})
        attrs["minimum_agent_version"] = version
        if len(attrs.get("reason", "").strip()) < 5:
            raise serializers.ValidationError({"reason": "Give a short justification."})
        return attrs


class HealthThresholdsViewSet(
    CustomerScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    serializer_class = HealthThresholdsSerializer
    pagination_class = None

    def get_customer(self) -> Any:
        self.customer_capability = (
            Cap.CUSTOMER_READ if self.action in ("list", "effective") else Cap.CUSTOMER_MANAGE_EXCEPTIONS
        )
        return super().get_customer()

    def get_queryset(self) -> QuerySet[HealthThresholds]:
        if getattr(self, "swagger_fake_view", False):
            return HealthThresholds.objects.none()
        return HealthThresholds.objects.filter(customer=self.get_customer()).select_related(
            "proposed_by", "reviewed_by"
        )[:50]

    def get_object(self) -> HealthThresholds:
        try:
            pk = uuid.UUID(str(self.kwargs["pk"]))
        except ValueError as exc:
            raise NotFound() from exc
        obj = HealthThresholds.objects.filter(customer=self.get_customer(), pk=pk).first()
        if obj is None:
            raise NotFound()
        return obj

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def effective(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(health.effective_thresholds(self.get_customer().id).as_dict())

    def perform_create(self, serializer: HealthThresholdsSerializer) -> None:
        customer = self.get_customer()
        try:
            with transaction.atomic():
                obj = serializer.save(customer=customer, proposed_by=self.request.user)
        except IntegrityError as exc:
            raise ValidationError({"detail": "A proposal is already awaiting review."}) from exc
        self._audit("health_thresholds.proposed", obj)

    def _audit(self, name: str, obj: HealthThresholds) -> None:
        record_event(
            action=name,
            outcome="success",
            actor=self.request.user,
            customer=obj.customer_id,
            target_type="health_thresholds",
            target_id=str(obj.id),
            request=self.request,
            metadata={
                "offline_hours": obj.offline_hours,
                "stale_days": obj.stale_days,
                "disk": [obj.disk_warning_free_pct, obj.disk_critical_free_pct],
                "minimum_agent_version": obj.minimum_agent_version,
            },
        )

    @extend_schema(request=None, responses={200: HealthThresholdsSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        obj = self.get_object()
        if obj.state != HealthThresholds.State.PROPOSED:
            raise ValidationError({"detail": f"Cannot approve thresholds in state '{obj.state}'."})
        if getattr(settings, "CATALOG_REQUIRE_SEPARATE_REVIEWER", True) and obj.proposed_by_id == request.user.pk:
            raise ValidationError({"detail": "A different administrator must approve these thresholds."})
        with transaction.atomic():
            HealthThresholds.objects.filter(customer_id=obj.customer_id, state=HealthThresholds.State.APPROVED).update(
                state=HealthThresholds.State.SUPERSEDED
            )
            obj.state, obj.reviewed_by, obj.reviewed_at = HealthThresholds.State.APPROVED, request.user, timezone.now()
            obj.save(update_fields=["state", "reviewed_by", "reviewed_at"])
        self._audit("health_thresholds.approved", obj)
        return Response(HealthThresholdsSerializer(obj).data)

    @extend_schema(request=None, responses={200: HealthThresholdsSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        obj = self.get_object()
        if obj.state != HealthThresholds.State.PROPOSED:
            raise ValidationError({"detail": f"Cannot reject thresholds in state '{obj.state}'."})
        obj.state, obj.reviewed_by, obj.reviewed_at = HealthThresholds.State.REJECTED, request.user, timezone.now()
        obj.save(update_fields=["state", "reviewed_by", "reviewed_at"])
        self._audit("health_thresholds.rejected", obj)
        return Response(HealthThresholdsSerializer(obj).data)
