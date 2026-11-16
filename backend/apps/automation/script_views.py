"""SCR-01: script collectors (super admin) and collected script values (per customer, read-only)."""

from __future__ import annotations

import re
from typing import Any

from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from .models import AutomationScript, DeviceScriptValue, ScriptCollector

_VAR = re.compile(r"^[A-Za-z0-9_.\- ]{1,100}$")
# Same spirit as the device custom-field allowlist: names that look like credentials are never collected.
_SECRETISH = re.compile(r"pass|secret|token|key|credential|pwd|pin\b", re.IGNORECASE)


class CollectorSerializer(serializers.ModelSerializer):
    script_name = serializers.SerializerMethodField()
    created_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = ScriptCollector
        fields = [
            "id",
            "integration_instance",
            "script_external_id",
            "script_name",
            "label",
            "allowed_variables",
            "enabled",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "script_name", "created_by", "created_at"]

    def get_script_name(self, obj: ScriptCollector) -> str:
        script = AutomationScript.objects.filter(
            integration_instance_id=obj.integration_instance_id, external_id=obj.script_external_id
        ).first()
        return script.name if script else ""

    def validate_allowed_variables(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not 1 <= len(value) <= 20:
            raise serializers.ValidationError("List 1 to 20 output variable names.")
        names = []
        for v in value:
            if not isinstance(v, str) or not _VAR.fullmatch(v.strip()):
                raise serializers.ValidationError("Variable names: letters, digits, space, _ . - (max 100).")
            if _SECRETISH.search(v):
                raise serializers.ValidationError(f"“{v}” looks like a credential and cannot be collected.")
            names.append(v.strip())
        return sorted(set(names))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = attrs.get("integration_instance", getattr(self.instance, "integration_instance", None))
        script = attrs.get("script_external_id", getattr(self.instance, "script_external_id", ""))
        if not AutomationScript.objects.filter(integration_instance=instance, external_id=script).exists():
            raise serializers.ValidationError({"script_external_id": "Pick a script from the collected catalog."})
        return attrs


class ScriptCollectorViewSet(viewsets.ModelViewSet):
    serializer_class = CollectorSerializer
    permission_classes = [IsSystemAdmin]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> QuerySet[ScriptCollector]:
        return ScriptCollector.objects.select_related("created_by").order_by("label")

    def _audit(self, verb: str, c: ScriptCollector) -> None:
        record_event(
            action=f"script_collector.{verb}",
            outcome="success",
            actor=self.request.user,
            target_type="script_collector",
            target_id=str(c.id),
            request=self.request,
            metadata={"script": c.script_external_id, "variables": c.allowed_variables, "enabled": c.enabled},
        )

    def perform_create(self, serializer: CollectorSerializer) -> None:
        self._audit("created", serializer.save(created_by=self.request.user))

    def perform_update(self, serializer: CollectorSerializer) -> None:
        self._audit("updated", serializer.save())

    def perform_destroy(self, instance: ScriptCollector) -> None:
        self._audit("deleted", instance)
        instance.delete()


class ScriptCatalogView(APIView):
    """``GET /automation/scripts/`` - collected script catalog for picking collectors (super admin)."""

    permission_classes = [IsSystemAdmin]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(
            [
                {
                    "integration_instance": str(s.integration_instance_id),
                    "id": s.external_id,
                    "name": s.name,
                    "category": s.category,
                    "platforms": s.platforms,
                    "folder": s.folder_path,
                }
                for s in AutomationScript.objects.order_by("name")
            ]
        )


class CustomerScriptCollectorsView(CustomerScopedMixin, APIView):
    """``GET /customers/{id}/script-collectors/`` - enabled collectors of this customer's sources (label + allowed
    variable names only), for building compliance rules and reports."""

    customer_capability = Cap.CUSTOMER_READ

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from apps.customers.models import CustomerSourceMapping

        instances = CustomerSourceMapping.objects.filter(
            customer=self.get_customer(), mapping_status="approved"
        ).values_list("integration_instance_id", flat=True)
        return Response(
            [
                {"id": str(c.id), "label": c.label, "allowed_variables": c.allowed_variables}
                for c in ScriptCollector.objects.filter(integration_instance_id__in=instances, enabled=True).order_by(
                    "label"
                )
            ]
        )


class CustomerScriptValueViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    """``/customers/{id}/script-values/?collector=&asset=`` - collected values for this customer's devices."""

    customer_capability = Cap.CUSTOMER_READ

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from apps.inventory.queries import current_observations

        customer = self.get_customer()
        qs = DeviceScriptValue.objects.filter(customer=customer, collector__enabled=True).select_related("collector")
        if collector := request.query_params.get("collector"):
            qs = qs.filter(collector_id=collector) if re.fullmatch(r"[0-9a-f-]{36}", collector) else qs.none()
        if asset := request.query_params.get("asset"):
            qs = qs.filter(asset_id=asset) if re.fullmatch(r"[0-9a-f-]{36}", asset) else qs.none()
        current = dict(current_observations(customer.id).values_list("asset_id", "hostname"))
        rows = [
            {
                "asset_id": str(v.asset_id),
                "hostname": current[v.asset_id],
                "collector_id": str(v.collector_id),
                "collector": v.collector.label,
                "state": v.state,
                "executed_at": v.executed_at.isoformat() if v.executed_at else None,
                "fetched_at": v.fetched_at.isoformat(),
                # Re-filter on read: a variable removed from the allowlist disappears immediately.
                "values": {k: x for k, x in v.values.items() if k in set(v.collector.allowed_variables)},
            }
            for v in qs
            if v.asset_id in current
        ]
        rows.sort(key=lambda r: (r["collector"].casefold(), r["hostname"].casefold()))
        collectors = sorted({(r["collector_id"], r["collector"]) for r in rows}, key=lambda c: c[1].casefold())
        return Response({"collectors": [{"id": i, "label": label} for i, label in collectors], "results": rows})
