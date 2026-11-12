from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import Cap
from apps.audit.services import record_event

from .models import IntegrationInstance


class IntegrationInstanceSerializer(serializers.ModelSerializer):
    """``credential_ref`` is write-only: responses only say whether one is configured."""

    credential_ref = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=200)
    credential_configured = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationInstance
        fields = [
            "id",
            "name",
            "provider",
            "base_url",
            "region",
            "credential_ref",
            "credential_configured",
            "enabled",
            "verify_tls",
            "max_rps",
            "status",
            "is_fixture",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "verify_tls", "status", "created_at", "updated_at", "credential_configured"]

    def get_credential_configured(self, obj: IntegrationInstance) -> bool:
        return bool(obj.credential_ref)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = self.instance or IntegrationInstance()
        if self.instance is not None and "provider" in attrs and attrs["provider"] != self.instance.provider:
            raise ValidationError({"provider": "Provider cannot be changed after creation."})
        if self.instance is not None and "is_fixture" in attrs and attrs["is_fixture"] != self.instance.is_fixture:
            raise ValidationError({"is_fixture": "Fixture/live designation cannot be changed after creation."})
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        attrs["base_url"] = instance.base_url
        return attrs


class IntegrationInstanceViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Global connector configuration (super admin). No delete: disable instead; mappings reference it."""

    serializer_class = IntegrationInstanceSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    queryset = IntegrationInstance.objects.all()

    def get_permissions(self) -> list[Any]:
        if self.action == "options_list":
            return [IsAuthenticated()]
        return [IsSystemAdmin()]

    def get_queryset(self) -> QuerySet[IntegrationInstance]:
        return IntegrationInstance.objects.all()

    def perform_create(self, serializer: IntegrationInstanceSerializer) -> None:
        inst = serializer.save()
        record_event(
            action="integration.created",
            outcome="success",
            actor=self.request.user,
            target_type="integration",
            target_id=str(inst.id),
            request=self.request,
            metadata={"provider": inst.provider, "base_url": inst.base_url, "is_fixture": inst.is_fixture},
        )

    def perform_update(self, serializer: IntegrationInstanceSerializer) -> None:
        changed = sorted(serializer.validated_data.keys())
        inst = serializer.save()
        record_event(
            action="integration.updated",
            outcome="success",
            actor=self.request.user,
            target_type="integration",
            target_id=str(inst.id),
            request=self.request,
            metadata={"changed": changed, "enabled": inst.enabled, "base_url": inst.base_url},
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="options")
    def options_list(self, request: Request) -> Response:
        """Minimal id/name/provider list for users who may propose source mappings."""
        user = request.user
        ids = scope.accessible_customer_ids(user, Cap.CUSTOMER_PROPOSE_MAPPINGS)
        if ids is not None and not ids:
            raise PermissionDenied()
        data = [
            {"id": str(i.id), "name": i.name, "provider": i.provider, "is_fixture": i.is_fixture}
            for i in IntegrationInstance.objects.order_by("provider", "name")
        ]
        return Response(data)
