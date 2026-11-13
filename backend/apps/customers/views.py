from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import DELEGABLE_ROLES, Cap
from apps.audit.services import record_event

from .models import Customer, CustomerMembership, CustomerSourceMapping
from .serializers import CustomerSerializer, MembershipSerializer, ReviewSerializer, SourceMappingSerializer


class CustomerScopedMixin:
    """Nested ``/customers/{customer_pk}/...`` views: resolve the customer from the DB and require a capability.

    The customer always comes from the URL + database + policy, never from request bodies.
    """

    customer_capability: str = Cap.CUSTOMER_READ
    request: Request
    kwargs: dict[str, Any]

    def get_customer(self) -> Customer:
        if not hasattr(self, "_customer"):
            self._customer = scope.get_customer_or_404(
                self.request.user, self.kwargs["customer_pk"], self.customer_capability, self.request
            )
        return self._customer

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        """Authorise the customer *before* any handler or input validation runs (VSAP-03).

        Without this, a create/update could return 400 (input validated) for a customer the caller may not access,
        revealing that it exists. Now every nested route answers 404 for unknown and unauthorised customers alike.
        """
        super().initial(request, *args, **kwargs)  # type: ignore[misc]  # authentication, permissions, throttling
        if "customer_pk" in self.kwargs and not getattr(self, "swagger_fake_view", False):
            self.get_customer()


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self) -> list[Any]:
        if self.action in {"create", "partial_update", "update", "destroy"}:
            return [IsSystemAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self) -> QuerySet[Customer]:
        if getattr(self, "swagger_fake_view", False):
            return Customer.objects.none()
        qs = scope.scope_queryset(Customer.objects.all(), self.request.user, Cap.CUSTOMER_READ, "self")
        if not self.request.user.is_super_admin:
            qs = qs.filter(status__in=Customer.MEMBER_VISIBLE_STATUSES)
        search = self.request.query_params.get("search", "").strip()[:100]
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        status_filter = self.request.query_params.get("status")
        if status_filter in Customer.Status.values:
            qs = qs.filter(status=status_filter)
        return qs

    def get_object(self) -> Customer:
        return scope.get_customer_or_404(self.request.user, self.kwargs["pk"], Cap.CUSTOMER_READ, self.request)

    def perform_create(self, serializer: CustomerSerializer) -> None:
        customer = serializer.save()
        record_event(
            action="customer.created",
            outcome="success",
            actor=self.request.user,
            customer=customer,
            target_type="customer",
            target_id=str(customer.id),
            request=self.request,
            metadata={"code": customer.code, "status": customer.status},
        )

    def perform_update(self, serializer: CustomerSerializer) -> None:
        changed = sorted(serializer.validated_data.keys())
        customer = serializer.save()
        record_event(
            action="customer.updated",
            outcome="success",
            actor=self.request.user,
            customer=customer,
            target_type="customer",
            target_id=str(customer.id),
            request=self.request,
            metadata={"changed": changed, "status": customer.status},
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Customers are archived, never hard-deleted (audit, report and history integrity)."""
        customer = self.get_object()
        customer.status = Customer.Status.ARCHIVED
        customer.save(update_fields=["status", "updated_at"])
        record_event(
            action="customer.archived",
            outcome="success",
            actor=request.user,
            customer=customer,
            target_type="customer",
            target_id=str(customer.id),
            request=request,
        )
        return Response(CustomerSerializer(customer, context={"request": request}).data)


class MembershipViewSet(
    CustomerScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    customer_capability = Cap.CUSTOMER_MANAGE_MEMBERS
    serializer_class = MembershipSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> QuerySet[CustomerMembership]:
        if getattr(self, "swagger_fake_view", False):
            return CustomerMembership.objects.none()
        qs = CustomerMembership.objects.filter(customer=self.get_customer()).select_related(
            "user", "role", "granted_by"
        )
        if self.request.query_params.get("include_revoked") != "true":
            qs = qs.filter(is_active=True)
        return qs

    def _check_delegation(self, role_key: str | None, target: CustomerMembership | None) -> None:
        user = self.request.user
        if target is not None and target.user_id == user.pk:
            raise PermissionDenied("You cannot change your own membership.")
        if user.is_super_admin:
            return
        if role_key is not None and role_key not in DELEGABLE_ROLES:
            raise PermissionDenied("Only a super administrator can grant this role.")
        if target is not None and target.role.key not in DELEGABLE_ROLES:
            raise PermissionDenied("Only a super administrator can change this membership.")

    def perform_create(self, serializer: MembershipSerializer) -> None:
        customer = self.get_customer()
        data = serializer.validated_data
        self._check_delegation(data["role"].key, None)
        if data["user"].pk == self.request.user.pk:
            raise PermissionDenied("You cannot grant yourself a membership.")
        existing = CustomerMembership.objects.filter(customer=customer, user=data["user"]).first()
        if existing is not None and existing.is_active:
            raise ValidationError({"email": "This user already has an active membership."})
        if existing is not None:
            self._check_delegation(data["role"].key, existing)
            existing.role = data["role"]
            existing.can_export = data.get("can_export", False)
            existing.is_active, existing.revoked_at, existing.granted_by = True, None, self.request.user
            existing.save()
            serializer.instance = existing
        else:
            serializer.save(customer=customer, granted_by=self.request.user)
        membership = serializer.instance
        scope.invalidate_cache(membership.user)
        record_event(
            action="membership.granted",
            outcome="success",
            actor=self.request.user,
            customer=customer,
            target_type="membership",
            target_id=str(membership.id),
            request=self.request,
            metadata={"user": membership.user.email, "role": membership.role.key, "can_export": membership.can_export},
        )

    def perform_update(self, serializer: MembershipSerializer) -> None:
        target = serializer.instance
        new_role = serializer.validated_data.get("role")
        self._check_delegation(new_role.key if new_role else None, target)
        membership = serializer.save()
        record_event(
            action="membership.updated",
            outcome="success",
            actor=self.request.user,
            customer=membership.customer,
            target_type="membership",
            target_id=str(membership.id),
            request=self.request,
            metadata={"user": membership.user.email, "role": membership.role.key, "can_export": membership.can_export},
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        membership = self.get_object()
        self._check_delegation(None, membership)
        membership.is_active = False
        membership.revoked_at = timezone.now()
        membership.save(update_fields=["is_active", "revoked_at", "updated_at"])
        record_event(
            action="membership.revoked",
            outcome="success",
            actor=request.user,
            customer=membership.customer,
            target_type="membership",
            target_id=str(membership.id),
            request=request,
            metadata={"user": membership.user.email, "role": membership.role.key},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SourceMappingViewSet(
    CustomerScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Customer-side mapping list and proposals. Approval is a super-admin review action."""

    customer_capability = Cap.CUSTOMER_PROPOSE_MAPPINGS
    serializer_class = SourceMappingSerializer

    def get_queryset(self) -> QuerySet[CustomerSourceMapping]:
        if getattr(self, "swagger_fake_view", False):
            return CustomerSourceMapping.objects.none()
        return CustomerSourceMapping.objects.filter(customer=self.get_customer()).select_related(
            "customer", "integration_instance", "proposed_by", "reviewed_by"
        )

    def perform_create(self, serializer: SourceMappingSerializer) -> None:
        customer = self.get_customer()
        try:
            with transaction.atomic():
                mapping = serializer.save(
                    customer=customer,
                    proposed_by=self.request.user,
                    mapping_status=CustomerSourceMapping.Status.PROPOSED,
                )
        except IntegrityError as exc:
            raise ValidationError(
                {"external_org_id": "This source organisation already has a proposed or approved mapping."}
            ) from exc
        record_event(
            action="mapping.proposed",
            outcome="success",
            actor=self.request.user,
            customer=customer,
            target_type="source_mapping",
            target_id=str(mapping.id),
            request=self.request,
            metadata={"integration": str(mapping.integration_instance_id), "external_org_id": mapping.external_org_id},
        )


class MappingReviewViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """System-wide mapping review queue (super admin). Approve / reject / revoke."""

    permission_classes = [IsSystemAdmin]
    serializer_class = SourceMappingSerializer

    def get_queryset(self) -> QuerySet[CustomerSourceMapping]:
        qs = CustomerSourceMapping.objects.select_related(
            "customer", "integration_instance", "proposed_by", "reviewed_by"
        )
        status_filter = self.request.query_params.get("status")
        if status_filter in CustomerSourceMapping.Status.values:
            qs = qs.filter(mapping_status=status_filter)
        return qs

    def _transition(self, request: Request, allowed_from: set[str], to: str, action_name: str) -> Response:
        review = ReviewSerializer(data=request.data)
        review.is_valid(raise_exception=True)
        with transaction.atomic():
            mapping = CustomerSourceMapping.objects.select_for_update().get(pk=self.get_object().pk)
            if mapping.mapping_status not in allowed_from:
                raise ValidationError({"mapping_status": f"Cannot {action_name} a {mapping.mapping_status} mapping."})
            mapping.mapping_status = to
            mapping.reviewed_by = request.user
            mapping.reviewed_at = timezone.now()
            mapping.review_note = review.validated_data.get("note", "")
            mapping.save()
        record_event(
            action=f"mapping.{action_name}",
            outcome="success",
            actor=request.user,
            customer=mapping.customer,
            target_type="source_mapping",
            target_id=str(mapping.id),
            request=request,
            metadata={"integration": str(mapping.integration_instance_id), "external_org_id": mapping.external_org_id},
        )
        return Response(self.get_serializer(mapping).data)

    @extend_schema(request=ReviewSerializer, responses={200: SourceMappingSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        S = CustomerSourceMapping.Status
        return self._transition(request, {S.PROPOSED}, S.APPROVED, "approved")

    @extend_schema(request=ReviewSerializer, responses={200: SourceMappingSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        S = CustomerSourceMapping.Status
        return self._transition(request, {S.PROPOSED}, S.REJECTED, "rejected")

    @extend_schema(request=ReviewSerializer, responses={200: SourceMappingSerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, pk: str | None = None) -> Response:
        S = CustomerSourceMapping.Status
        return self._transition(request, {S.APPROVED}, S.REVOKED, "revoked")
