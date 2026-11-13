"""VSA4-03 API: ``/customers/{id}/notifications/`` (read) and ``/customers/{id}/custom-field-allowlist/``."""

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

from . import details
from .models import CustomFieldAllowlist, DeviceNotification
from .queries import current_generations


class NotificationSerializer(serializers.ModelSerializer):
    hostname = serializers.CharField(source="fetch.observation.hostname", read_only=True)

    class Meta:
        model = DeviceNotification
        fields = [
            "id",
            "asset",
            "hostname",
            "vendor_id",
            "priority",
            "occurred_at",
            "occurred_raw",
            "message",
            "redactions",
        ]
        read_only_fields = fields


class CustomerNotificationViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    customer_capability = Cap.CUSTOMER_READ
    serializer_class = NotificationSerializer

    def get_queryset(self) -> QuerySet[DeviceNotification]:
        if getattr(self, "swagger_fake_view", False):
            return DeviceNotification.objects.none()
        customer = self.get_customer()
        qs = DeviceNotification.objects.filter(
            customer=customer, generation__in=current_generations(customer.pk)
        ).select_related("fetch__observation")
        p = self.request.query_params
        if pr := p.get("priority"):
            qs = qs.filter(priority=pr[:32].lower())
        if q := p.get("q", "").strip()[:100]:
            qs = qs.filter(message__icontains=q)
        if asset := p.get("asset"):
            try:
                qs = qs.filter(asset_id=uuid.UUID(asset))
            except ValueError as exc:
                raise ValidationError({"asset": "Not a valid ID."}) from exc
        return qs.order_by("-occurred_at", "id")

    @extend_schema(
        parameters=[OpenApiParameter("priority", str), OpenApiParameter("q", str), OpenApiParameter("asset", str)],
        responses={200: NotificationSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(details.summary(self.get_customer().id))


class CustomFieldAllowlistSerializer(serializers.ModelSerializer):
    proposed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = CustomFieldAllowlist
        fields = ["id", "name", "reason", "state", "proposed_by", "reviewed_by", "reviewed_at", "created_at"]
        read_only_fields = ["id", "state", "proposed_by", "reviewed_by", "reviewed_at", "created_at"]

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Enter the exact VSA custom field name.")
        if details.is_sensitive_field_name(name):
            raise serializers.ValidationError(
                "Credential-like fields (passwords, keys, tokens, PINs...) cannot be approved."
            )
        return name

    def validate_reason(self, value: str) -> str:
        if len(value.strip()) < 5:
            raise serializers.ValidationError("Give a short justification.")
        return value.strip()


class CustomFieldAllowlistViewSet(
    CustomerScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    serializer_class = CustomFieldAllowlistSerializer
    pagination_class = None

    def get_customer(self) -> Any:
        self.customer_capability = Cap.CUSTOMER_READ if self.action == "list" else Cap.CUSTOMER_MANAGE_EXCEPTIONS
        return super().get_customer()

    def get_queryset(self) -> QuerySet[CustomFieldAllowlist]:
        if getattr(self, "swagger_fake_view", False):
            return CustomFieldAllowlist.objects.none()
        return CustomFieldAllowlist.objects.filter(customer=self.get_customer()).select_related(
            "proposed_by", "reviewed_by"
        )

    def get_object(self) -> CustomFieldAllowlist:
        try:
            pk = uuid.UUID(str(self.kwargs["pk"]))
        except ValueError as exc:
            raise NotFound() from exc
        obj = CustomFieldAllowlist.objects.filter(customer=self.get_customer(), pk=pk).first()
        if obj is None:
            raise NotFound()
        return obj

    def perform_create(self, serializer: CustomFieldAllowlistSerializer) -> None:
        customer = self.get_customer()
        name = serializer.validated_data["name"]
        try:
            with transaction.atomic():
                obj = serializer.save(customer=customer, proposed_by=self.request.user, name_key=name.casefold())
        except IntegrityError as exc:
            raise ValidationError({"name": "This field is already proposed or approved."}) from exc
        self._audit("custom_field_allowlist.proposed", obj)

    def _audit(self, name: str, obj: CustomFieldAllowlist) -> None:
        record_event(
            action=name,
            outcome="success",
            actor=self.request.user,
            customer=obj.customer_id,
            target_type="custom_field_allowlist",
            target_id=str(obj.id),
            request=self.request,
            metadata={"field": obj.name},
        )

    def _transition(self, allowed: set[str], to: str, name: str, *, separate: bool = False) -> Response:
        obj = self.get_object()
        if obj.state not in allowed:
            raise ValidationError({"detail": f"Cannot {name} a field in state '{obj.state}'."})
        if (
            separate
            and getattr(settings, "CATALOG_REQUIRE_SEPARATE_REVIEWER", True)
            and obj.proposed_by_id == self.request.user.pk
        ):
            raise ValidationError({"detail": "A different administrator must approve this field."})
        obj.state, obj.reviewed_by, obj.reviewed_at = to, self.request.user, timezone.now()
        obj.save(update_fields=["state", "reviewed_by", "reviewed_at"])
        self._audit(f"custom_field_allowlist.{name}", obj)
        return Response(CustomFieldAllowlistSerializer(obj).data)

    @extend_schema(request=None, responses={200: CustomFieldAllowlistSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"proposed"}, "approved", "approved", separate=True)

    @extend_schema(request=None, responses={200: CustomFieldAllowlistSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"proposed"}, "rejected", "rejected")

    @extend_schema(request=None, responses={200: CustomFieldAllowlistSerializer})
    @action(detail=True, methods=["post"])
    def retire(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"approved"}, "retired", "retired")
