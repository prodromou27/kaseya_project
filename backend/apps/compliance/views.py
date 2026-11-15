"""``/customers/{id}/compliance-baselines/`` — portal-owned rules, evaluated live against the current inventory."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from . import engine
from .models import BaselineRule, ComplianceBaseline

MAX_RULES = 30


class RuleSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()

    class Meta:
        model = BaselineRule
        fields = ["id", "kind", "params", "severity", "label"]
        read_only_fields = ["id", "label"]

    def get_label(self, obj: BaselineRule) -> str:
        return engine.describe(obj.kind, obj.params)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs["params"] = engine.clean_params(attrs["kind"], attrs.get("params", {}))
        return attrs


class BaselineSerializer(serializers.ModelSerializer):
    rules = RuleSerializer(many=True)
    created_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = ComplianceBaseline
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "scope_device_type",
            "scope_site_external_id",
            "scope_group_external_id",
            "rules",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A name is required.")
        customer = self.context["customer"]
        clash = ComplianceBaseline.objects.filter(customer=customer, name__iexact=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A baseline with this name already exists.")
        return value

    def validate_rules(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not value:
            raise serializers.ValidationError("Add at least one rule.")
        if len(value) > MAX_RULES:
            raise serializers.ValidationError(f"At most {MAX_RULES} rules per baseline.")
        return value

    def _write_rules(self, baseline: ComplianceBaseline, rules: list[dict[str, Any]]) -> None:
        baseline.rules.all().delete()
        BaselineRule.objects.bulk_create(
            [BaselineRule(baseline=baseline, position=i, **r) for i, r in enumerate(rules)]
        )

    def create(self, validated_data: dict[str, Any]) -> ComplianceBaseline:
        rules = validated_data.pop("rules")
        with transaction.atomic():
            baseline = ComplianceBaseline.objects.create(**validated_data)
            self._write_rules(baseline, rules)
        return baseline

    def update(self, instance: ComplianceBaseline, validated_data: dict[str, Any]) -> ComplianceBaseline:
        rules = validated_data.pop("rules", None)
        with transaction.atomic():
            for k, v in validated_data.items():
                setattr(instance, k, v)
            instance.save()
            if rules is not None:
                self._write_rules(instance, rules)
        return instance


def _filter_devices(devices: list[dict[str, Any]], params: Any) -> list[dict[str, Any]]:
    status = params.get("status", "")
    rule = params.get("rule", "")
    search = str(params.get("search", ""))[:100].casefold().strip()
    site, group = params.get("site", ""), params.get("group_id", "")
    out = devices
    if status in (engine.PASS, engine.FAIL, engine.UNKNOWN):
        out = [d for d in out if d["status"] == status]
    if rule:
        out = [d for d in out if any(r["rule_id"] == rule and r["state"] == engine.FAIL for r in d["results"])]
    if site:
        out = [d for d in out if d["site_external_id"] == site]
    if group:
        out = [d for d in out if d["group_external_id"] == group]
    if search:
        out = [d for d in out if search in d["hostname"].casefold()]
    return out


class ComplianceBaselineViewSet(CustomerScopedMixin, viewsets.ModelViewSet):
    serializer_class = BaselineSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_customer(self) -> Any:
        self.customer_capability = (
            Cap.CUSTOMER_READ if self.request.method in ("GET", "HEAD", "OPTIONS") else Cap.CUSTOMER_MANAGE_EXCEPTIONS
        )
        return super().get_customer()

    def get_queryset(self) -> QuerySet[ComplianceBaseline]:
        if getattr(self, "swagger_fake_view", False):
            return ComplianceBaseline.objects.none()
        return ComplianceBaseline.objects.filter(customer=self.get_customer()).prefetch_related("rules")

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False) and "customer_pk" in self.kwargs:
            ctx["customer"] = self.get_customer()
        return ctx

    def _audit(self, verb: str, baseline: ComplianceBaseline) -> None:
        record_event(
            action=f"compliance_baseline.{verb}",
            outcome="success",
            actor=self.request.user,
            customer=baseline.customer,
            target_type="compliance_baseline",
            target_id=str(baseline.id),
            request=self.request,
            metadata={
                "name": baseline.name,
                "rules": [r.kind for r in baseline.rules.all()],
                "enabled": baseline.enabled,
            },
        )

    def perform_create(self, serializer: BaselineSerializer) -> None:
        baseline = serializer.save(customer=self.get_customer(), created_by=self.request.user)
        self._audit("created", baseline)

    def perform_update(self, serializer: BaselineSerializer) -> None:
        self._audit("updated", serializer.save())

    def perform_destroy(self, instance: ComplianceBaseline) -> None:
        self._audit("deleted", instance)
        instance.delete()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get"])
    def results(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Per-device results for one baseline, with rule counts and a group breakdown. Filterable and paged."""
        baseline = self.get_object()
        result = engine.evaluate(baseline, engine.load_facts(baseline.customer_id))
        all_devices = result.pop("devices")
        result["groups"] = engine.group_breakdown(all_devices)
        devices = _filter_devices(all_devices, request.query_params)
        devices.sort(
            key=lambda d: (
                {"fail": 0, "unknown": 1, "pass": 2}[d["status"]],
                -d["failed_high"],
                -d["failed"],
                d["hostname"],
            )
        )
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except ValueError:
            page = 1
        size = 50
        return Response(
            {
                **result,
                "count": len(devices),
                "page": page,
                "page_size": size,
                "results": devices[(page - 1) * size : page * size],
            }
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def overview(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Score and totals of every enabled baseline (facts loaded once), plus the worst groups."""
        customer = self.get_customer()
        baselines = list(self.get_queryset().filter(enabled=True))
        facts = engine.load_facts(customer.id) if baselines else []
        rows = []
        for b in baselines:
            r = engine.evaluate(b, facts)
            rows.append(
                {
                    "id": str(b.id),
                    "name": b.name,
                    "devices_in_scope": r["devices_in_scope"],
                    "totals": r["totals"],
                    "score_pct": r["score_pct"],
                    "rules": r["rules"],
                    "groups": engine.group_breakdown(r["devices"])[:10],
                }
            )
        return Response(
            {"baselines": rows, "rule_kinds": [{"kind": k, "label": label} for k, label in BaselineRule.Kind.choices]}
        )
