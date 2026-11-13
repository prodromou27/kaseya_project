"""VSA3-04 API: ``/customers/{id}/patch-policies/`` (read) and ``/customers/{id}/patch-policy-baselines/``.

Baselines: propose/approve/reject/retire need ``customer.manage_exceptions``; approval must come from a different
user than the proposer (same rule as the software catalog, ``CATALOG_REQUIRE_SEPARATE_REVIEWER``).
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
from apps.inventory.models import GroupNode, OrganizationNode, SiteNode
from apps.inventory.queries import current_generations

from . import policy_queries
from .models import ExpectedPatchPolicy, PatchPolicyDefinition


class CustomerPatchPolicyViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    customer_capability = Cap.CUSTOMER_READ

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(policy_queries.summary(self.get_customer().id))

    @extend_schema(
        parameters=[
            OpenApiParameter("patch_state", str),
            OpenApiParameter("drift", str),
            OpenApiParameter("policy_id", str),
            OpenApiParameter("group_id", str),
            OpenApiParameter("q", str),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def devices(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        rows = policy_queries.filter_rows(policy_queries.device_rows(self.get_customer().id), request.query_params)
        page = self.paginate_queryset(rows)  # type: ignore[arg-type]
        return self.get_paginated_response(page)


class ExpectedPatchPolicySerializer(serializers.ModelSerializer):
    proposed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = ExpectedPatchPolicy
        fields = [
            "id",
            "scope_type",
            "scope_external_id",
            "expect_no_policy",
            "expected_policy_id",
            "expected_policy_name",
            "reason",
            "state",
            "proposed_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "expected_policy_name",
            "state",
            "proposed_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not str(attrs.get("scope_external_id", "")).isdigit():
            raise serializers.ValidationError({"scope_external_id": "Use the VSA numeric ID."})
        pid = attrs.get("expected_policy_id", "")
        if attrs.get("expect_no_policy"):
            if pid:
                raise serializers.ValidationError({"expected_policy_id": "Leave empty when expecting no policy."})
        elif not str(pid).isdigit():
            raise serializers.ValidationError({"expected_policy_id": "Choose a patch policy ID."})
        if len(attrs.get("reason", "").strip()) < 5:
            raise serializers.ValidationError({"reason": "Give a short justification."})
        return attrs


class ExpectedPatchPolicyViewSet(
    CustomerScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    serializer_class = ExpectedPatchPolicySerializer
    pagination_class = None

    def get_customer(self) -> Any:
        self.customer_capability = Cap.CUSTOMER_READ if self.action == "list" else Cap.CUSTOMER_MANAGE_EXCEPTIONS
        return super().get_customer()

    def get_queryset(self) -> QuerySet[ExpectedPatchPolicy]:
        if getattr(self, "swagger_fake_view", False):
            return ExpectedPatchPolicy.objects.none()
        return ExpectedPatchPolicy.objects.filter(customer=self.get_customer()).select_related(
            "proposed_by", "reviewed_by"
        )

    def get_object(self) -> ExpectedPatchPolicy:
        try:
            pk = uuid.UUID(str(self.kwargs["pk"]))
        except ValueError as exc:
            raise NotFound() from exc
        obj = self.get_queryset().filter(pk=pk).first()
        if obj is None:
            raise NotFound()
        return obj

    def perform_create(self, serializer: ExpectedPatchPolicySerializer) -> None:
        customer = self.get_customer()
        d = serializer.validated_data
        gens = list(current_generations(customer.pk))
        node_model = {"organization": OrganizationNode, "site": SiteNode, "group": GroupNode}[d["scope_type"]]
        if not node_model.objects.filter(
            customer=customer, generation__in=gens, external_id=d["scope_external_id"]
        ).exists():
            raise ValidationError({"scope_external_id": "Not an organisation/site/group in this customer's snapshot."})
        name = ""
        if not d.get("expect_no_policy"):
            definition = PatchPolicyDefinition.objects.filter(
                customer=customer, generation__in=gens, policy_id=d["expected_policy_id"]
            ).first()
            if definition is None:
                raise ValidationError(
                    {"expected_policy_id": "Not a patch policy referenced in this customer's snapshot."}
                )
            name = definition.name
        try:
            with transaction.atomic():
                obj = serializer.save(customer=customer, proposed_by=self.request.user, expected_policy_name=name)
        except IntegrityError as exc:
            raise ValidationError(
                {"scope_external_id": "An active expectation already exists for this scope."}
            ) from exc
        self._audit("patch_baseline.proposed", obj)

    def _audit(self, action_name: str, obj: ExpectedPatchPolicy) -> None:
        record_event(
            action=action_name,
            outcome="success",
            actor=self.request.user,
            customer=obj.customer_id,
            target_type="expected_patch_policy",
            target_id=str(obj.id),
            request=self.request,
            metadata={"scope": f"{obj.scope_type}:{obj.scope_external_id}", "policy": obj.expected_policy_id or "none"},
        )

    def _transition(self, allowed: set[str], to: str, action_name: str, *, separate: bool = False) -> Response:
        obj = self.get_object()
        if obj.state not in allowed:
            raise ValidationError({"detail": f"Cannot {action_name} an expectation in state '{obj.state}'."})
        if (
            separate
            and getattr(settings, "CATALOG_REQUIRE_SEPARATE_REVIEWER", True)
            and obj.proposed_by_id == self.request.user.pk
        ):
            raise ValidationError({"detail": "A different administrator must approve this expectation."})
        obj.state, obj.reviewed_by, obj.reviewed_at = to, self.request.user, timezone.now()
        obj.save(update_fields=["state", "reviewed_by", "reviewed_at"])
        self._audit(f"patch_baseline.{action_name}", obj)
        return Response(ExpectedPatchPolicySerializer(obj).data)

    @extend_schema(request=None, responses={200: ExpectedPatchPolicySerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"proposed"}, "approved", "approved", separate=True)

    @extend_schema(request=None, responses={200: ExpectedPatchPolicySerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"proposed"}, "rejected", "rejected")

    @extend_schema(request=None, responses={200: ExpectedPatchPolicySerializer})
    @action(detail=True, methods=["post"])
    def retire(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._transition({"approved"}, "retired", "retired")
