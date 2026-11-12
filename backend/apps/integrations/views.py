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

from .models import IntegrationInstance, SyncQuarantine, SyncSchedule


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
            "installed_updates_budget",
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
    @action(detail=True, methods=["get"])
    def organizations(self, request: Request, pk: str | None = None) -> Response:
        """Live (or fixture) list of source organisations with their mapping status. One read-only API crawl."""
        instance = self.get_object()
        record_event(
            action="integration.discovery",
            outcome="success",
            actor=request.user,
            target_type="integration",
            target_id=str(instance.id),
            request=request,
        )
        return _discover_organizations(instance)

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


class SyncQuarantineSerializer(serializers.ModelSerializer):
    integration = serializers.CharField(source="integration_instance.name", read_only=True)

    class Meta:
        model = SyncQuarantine
        fields = [
            "id",
            "sync_run",
            "integration",
            "external_id",
            "external_org_id",
            "reason",
            "snapshot",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = fields


class SyncQuarantineViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Quarantined source records — cross-customer by nature, therefore super admin only."""

    permission_classes = [IsSystemAdmin]
    serializer_class = SyncQuarantineSerializer
    queryset = SyncQuarantine.objects.select_related("integration_instance").all()

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        reason = self.request.query_params.get("reason", "").strip()[:64]
        return qs.filter(reason=reason) if reason else qs


def _discover_organizations(instance: IntegrationInstance) -> Response:
    from apps.customers.models import CustomerSourceMapping

    from .http import ConnectorError
    from .secrets import CredentialUnavailable
    from .vsa.adapter import VsaXAdapter
    from .vsa.schema import PageInvalid

    if instance.provider != IntegrationInstance.Provider.VSA_X:
        raise ValidationError({"detail": "Organisation discovery is implemented for VSA X only."})
    try:
        orgs, invalid = VsaXAdapter(instance).list_organizations()
    except (ConnectorError, CredentialUnavailable, PageInvalid) as exc:
        code = getattr(exc, "code", "credential_unavailable" if isinstance(exc, CredentialUnavailable) else "bad_page")
        raise ValidationError({"detail": f"Discovery failed: {code}."}) from exc
    mappings = {
        m.external_org_id: m
        for m in CustomerSourceMapping.objects.filter(
            integration_instance=instance, mapping_status__in=["proposed", "approved"]
        ).select_related("customer")
    }
    return Response(
        {
            "data_basis": "fixture" if instance.is_fixture else "live",
            "invalid_records": len(invalid),
            "organizations": [
                {
                    "external_org_id": o.id,
                    "name": o.name,
                    "type": o.type,
                    "mapping": None
                    if o.id not in mappings
                    else {
                        "id": str(mappings[o.id].id),
                        "status": mappings[o.id].mapping_status,
                        "customer": {"id": str(mappings[o.id].customer_id), "code": mappings[o.id].customer.code},
                    },
                }
                for o in orgs
            ],
        }
    )


class SyncScheduleSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    integration = serializers.CharField(source="mapping.integration_instance.name", read_only=True)
    external_org_id = serializers.CharField(source="mapping.external_org_id", read_only=True)

    class Meta:
        model = SyncSchedule
        fields = [
            "id",
            "mapping",
            "customer",
            "integration",
            "external_org_id",
            "interval_hours",
            "enabled",
            "next_run_at",
            "last_run_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "customer",
            "integration",
            "external_org_id",
            "next_run_at",
            "last_run_at",
            "created_at",
        ]

    def get_customer(self, obj: SyncSchedule) -> dict[str, str]:
        return {"id": str(obj.mapping.customer_id), "code": obj.mapping.customer.code}

    def validate_mapping(self, value: Any) -> Any:
        if value.mapping_status != "approved":
            raise ValidationError("Only approved mappings can be scheduled.")
        return value


class SyncScheduleViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Scheduled read-only collection (super admin). Dispatched by Celery Beat."""

    permission_classes = [IsSystemAdmin]
    serializer_class = SyncScheduleSerializer
    queryset = SyncSchedule.objects.select_related("mapping", "mapping__customer", "mapping__integration_instance")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_create(self, serializer: SyncScheduleSerializer) -> None:
        from django.utils import timezone

        s = serializer.save(next_run_at=timezone.now())
        record_event(
            action="sync.schedule_saved",
            outcome="success",
            actor=self.request.user,
            customer=s.mapping.customer,
            target_type="sync_schedule",
            target_id=str(s.id),
            request=self.request,
            metadata={"interval_hours": s.interval_hours},
        )

    def perform_update(self, serializer: SyncScheduleSerializer) -> None:
        s = serializer.save()
        record_event(
            action="sync.schedule_saved",
            outcome="success",
            actor=self.request.user,
            customer=s.mapping.customer,
            target_type="sync_schedule",
            target_id=str(s.id),
            request=self.request,
            metadata={"interval_hours": s.interval_hours, "enabled": s.enabled},
        )
