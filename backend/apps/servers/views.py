"""SRV-01 API: owner groups, server list with patch/upgrade needs, bulk marking/assignment. Portal-only data."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from . import status as server_status
from .models import ServerDesignation, ServerOwnerGroup

WRITE = Cap.CUSTOMER_MANAGE_EXCEPTIONS


class OwnerGroupSerializer(serializers.ModelSerializer):
    servers = serializers.SerializerMethodField()

    class Meta:
        model = ServerOwnerGroup
        fields = ["id", "name", "owner_name", "owner_email", "notes", "servers", "created_at", "updated_at"]
        read_only_fields = ["id", "servers", "created_at", "updated_at"]

    def get_servers(self, obj: ServerOwnerGroup) -> int:
        return getattr(obj, "_servers", 0)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        customer = self.context["customer"]
        qs = ServerOwnerGroup.objects.filter(customer=customer, name__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if not value or qs.exists():
            raise serializers.ValidationError("Use a unique, non-empty name for this customer.")
        return value


class OwnerGroupViewSet(
    CustomerScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """``/customers/{id}/server-owner-groups/`` - read: customer.read; change: customer administrators."""

    serializer_class = OwnerGroupSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_customer(self) -> Any:
        self.customer_capability = Cap.CUSTOMER_READ if self.request.method in ("GET", "HEAD", "OPTIONS") else WRITE
        return super().get_customer()

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return ServerOwnerGroup.objects.none()
        return ServerOwnerGroup.objects.filter(customer=self.get_customer())

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False):
            ctx["customer"] = self.get_customer()
        return ctx

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        groups = list(self.get_queryset())
        counts: dict[str, int] = {}
        for r in server_status.rows(self.get_customer().id):
            if r["owner_group_id"]:
                counts[r["owner_group_id"]] = counts.get(r["owner_group_id"], 0) + 1
        for g in groups:
            g._servers = counts.get(str(g.id), 0)
        return Response(OwnerGroupSerializer(groups, many=True, context=self.get_serializer_context()).data)

    def _audit(self, action_name: str, group: ServerOwnerGroup) -> None:
        record_event(
            action=action_name,
            outcome="success",
            actor=self.request.user,
            customer=group.customer,
            target_type="server_owner_group",
            target_id=str(group.id),
            request=self.request,
            metadata={"name": group.name},  # owner contact details are not copied into the audit trail
        )

    def perform_create(self, serializer: OwnerGroupSerializer) -> None:
        self._audit(
            "server_owner_group.created",
            serializer.save(customer=self.get_customer(), created_by=self.request.user),
        )

    def perform_update(self, serializer: OwnerGroupSerializer) -> None:
        self._audit("server_owner_group.updated", serializer.save())

    def perform_destroy(self, instance: ServerOwnerGroup) -> None:
        self._audit("server_owner_group.deleted", instance)
        instance.delete()  # its servers become unassigned (SET_NULL)


class DesignateInput(serializers.Serializer):
    assets = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=500)
    # "server" = mark as server, "not_server" = never treat as server, "auto" = follow OS-name detection.
    marking = serializers.ChoiceField(choices=["server", "not_server", "auto"], required=False)
    # UUID of an owner group, "" to unassign; omitted = unchanged.
    owner_group = serializers.CharField(required=False, allow_blank=True, max_length=40)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class ServerViewSet(CustomerScopedMixin, viewsets.ViewSet):
    """``/customers/{id}/servers/`` - servers with owner and patch/upgrade needs."""

    def get_customer(self) -> Any:
        self.customer_capability = WRITE if self.action == "designate" else Cap.CUSTOMER_READ
        return super().get_customer()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request: Request, customer_pk: str | None = None) -> Response:
        customer = self.get_customer()
        params = request.query_params
        include_all = params.get("scope") == "all"
        data = server_status.rows(customer.id, include_all=include_all)
        owner = params.get("owner_group", "")
        if owner == "none":
            data = [r for r in data if not r["owner_group_id"]]
        elif owner:
            data = [r for r in data if r["owner_group_id"] == owner]
        if params.get("attention") == "true":
            data = [r for r in data if r["needs_attention"]]
        search = (params.get("search") or "").strip().casefold()[:100]
        if search:
            data = [
                r
                for r in data
                if search in r["hostname"].casefold()
                or search in r["os_name"].casefold()
                or search in r["owner_group"].casefold()
            ]
        return Response(
            {
                "rows": data[:2000],
                "count": len(data),
                "totals": server_status.summary(data),
                "detection_note": "Devices whose reported operating system name contains 'Server' are detected "
                "automatically. Mark other devices as servers, or mark a detected device as not a server.",
            }
        )

    @extend_schema(request=DesignateInput, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def designate(self, request: Request, customer_pk: str | None = None) -> Response:
        customer = self.get_customer()
        data = DesignateInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if "marking" not in v and "owner_group" not in v and "note" not in v:
            raise ValidationError({"marking": "Choose what to change."})
        from apps.inventory.models import Asset

        assets = list(Asset.objects.filter(customer=customer, pk__in=v["assets"]).values_list("pk", flat=True))
        if len(assets) != len(set(v["assets"])):
            raise ValidationError({"assets": "One or more devices were not found for this customer."})
        group = None
        if v.get("owner_group"):
            group = ServerOwnerGroup.objects.filter(customer=customer, pk=_uuid(v["owner_group"])).first()
            if group is None:
                raise ValidationError({"owner_group": "Owner group not found for this customer."})
        marking = {"server": True, "not_server": False, "auto": None}.get(v.get("marking", ""), "keep")
        with transaction.atomic():
            for asset_id in assets:
                d, _ = ServerDesignation.objects.get_or_create(
                    asset_id=asset_id, defaults={"customer": customer, "updated_by": request.user}
                )
                if marking != "keep":
                    d.is_server = marking
                if "owner_group" in v:
                    d.owner_group = group
                if "note" in v:
                    d.note = v["note"]
                d.updated_by = request.user
                d.save()
        record_event(
            action="server.designated",
            outcome="success",
            actor=request.user,
            customer=customer,
            target_type="server_designation",
            target_id=str(assets[0]) if len(assets) == 1 else "",
            request=request,
            metadata={
                "devices": len(assets),
                "marking": v.get("marking", "unchanged"),
                "owner_group_id": str(group.id) if group else ("" if "owner_group" in v else "unchanged"),
            },
        )
        return Response({"updated": len(assets)}, status=status.HTTP_200_OK)


def _uuid(value: str) -> Any:
    import uuid

    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValidationError({"owner_group": "Owner group not found for this customer."}) from exc
