"""VSA2-05 API: ``/customers/{id}/expected-subnets/`` — reviewed expected subnets per site/group.

Propose/approve/reject/retire require ``customer.manage_exceptions``; approval by a different user than the proposer.
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from .models import ExpectedSubnet, GroupNode, SiteNode
from .queries import current_generations


class ExpectedSubnetSerializer(serializers.ModelSerializer):
    proposed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    integration_instance = serializers.UUIDField(source="integration_instance_id", required=False, allow_null=True)

    class Meta:
        model = ExpectedSubnet
        fields = [
            "id",
            "integration_instance",
            "scope_type",
            "scope_external_id",
            "cidr",
            "reason",
            "state",
            "proposed_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = ["id", "state", "proposed_by", "reviewed_by", "reviewed_at", "created_at"]

    def validate_cidr(self, value: str) -> str:
        try:
            net = ipaddress.ip_network(value.strip(), strict=True)
        except ValueError as exc:
            raise serializers.ValidationError(
                "Use a network in CIDR form with no host bits, e.g. 10.1.10.0/24."
            ) from exc
        if net.prefixlen == 0:
            raise serializers.ValidationError("A /0 network matches everything and is not a meaningful expectation.")
        return str(net)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not str(attrs.get("scope_external_id", "")).isdigit():
            raise serializers.ValidationError({"scope_external_id": "Use the VSA numeric ID."})
        if len(attrs.get("reason", "").strip()) < 5:
            raise serializers.ValidationError({"reason": "Give a short justification."})
        return attrs


class ExpectedSubnetViewSet(
    CustomerScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    serializer_class = ExpectedSubnetSerializer
    pagination_class = None

    def get_customer(self) -> Any:
        self.customer_capability = Cap.CUSTOMER_READ if self.action == "list" else Cap.CUSTOMER_MANAGE_EXCEPTIONS
        return super().get_customer()

    def get_queryset(self) -> QuerySet[ExpectedSubnet]:
        if getattr(self, "swagger_fake_view", False):
            return ExpectedSubnet.objects.none()
        qs = ExpectedSubnet.objects.filter(customer=self.get_customer()).select_related("proposed_by", "reviewed_by")
        if scope := self.request.query_params.get("scope"):
            kind, _, sid = scope.partition(":")
            qs = qs.filter(scope_type=kind[:8], scope_external_id=sid[:20])
        return qs

    def get_object(self) -> ExpectedSubnet:
        try:
            pk = uuid.UUID(str(self.kwargs["pk"]))
        except ValueError as exc:
            raise NotFound() from exc
        obj = ExpectedSubnet.objects.filter(customer=self.get_customer(), pk=pk).first()
        if obj is None:
            raise NotFound()
        return obj

    def perform_create(self, serializer: ExpectedSubnetSerializer) -> None:
        customer = self.get_customer()
        d = serializer.validated_data
        node = SiteNode if d["scope_type"] == "site" else GroupNode
        sources = node.objects.filter(
            customer=customer, generation__in=current_generations(customer.pk), external_id=d["scope_external_id"]
        )
        if d.get("integration_instance_id"):
            sources = sources.filter(generation__integration_instance_id=d["integration_instance_id"])
        ids = set(sources.values_list("generation__integration_instance_id", flat=True))
        if len(ids) != 1:
            raise ValidationError({"integration_instance": "Select one source containing this customer's site/group."})
        d.pop("integration_instance_id", None)
        instance_id = ids.pop()
        try:
            with transaction.atomic():
                obj = serializer.save(
                    customer=customer, proposed_by=self.request.user, integration_instance_id=instance_id
                )
        except IntegrityError as exc:
            raise ValidationError({"cidr": "This subnet is already proposed or approved for the scope."}) from exc
        self._audit("expected_subnet.proposed", obj)

    def _audit(self, name: str, obj: ExpectedSubnet) -> None:
        record_event(
            action=name,
            outcome="success",
            actor=self.request.user,
            customer=obj.customer_id,
            target_type="expected_subnet",
            target_id=str(obj.id),
            request=self.request,
            metadata={"scope": f"{obj.scope_type}:{obj.scope_external_id}", "cidr": obj.cidr},
        )

    def _transition(self, allowed: set[str], to: str, name: str, *, separate: bool = False) -> Response:
        obj = self.get_object()
        if obj.state not in allowed:
            raise ValidationError({"detail": f"Cannot {name} a subnet in state '{obj.state}'."})
        if (
            separate
            and getattr(settings, "CATALOG_REQUIRE_SEPARATE_REVIEWER", True)
            and obj.proposed_by_id == self.request.user.pk
        ):
            raise ValidationError({"detail": "A different administrator must approve this subnet."})
        obj.state, obj.reviewed_by, obj.reviewed_at = to, self.request.user, timezone.now()
        obj.save(update_fields=["state", "reviewed_by", "reviewed_at"])
        self._audit(f"expected_subnet.{name}", obj)
        return Response(ExpectedSubnetSerializer(obj).data)

    @extend_schema(request=None, responses={200: ExpectedSubnetSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"proposed"}, "approved", "approved", separate=True)

    @extend_schema(request=None, responses={200: ExpectedSubnetSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"proposed"}, "rejected", "rejected")

    @extend_schema(request=None, responses={200: ExpectedSubnetSerializer})
    @action(detail=True, methods=["post"])
    def retire(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"approved"}, "retired", "retired")
