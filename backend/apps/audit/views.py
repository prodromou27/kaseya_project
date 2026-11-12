from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import mixins, serializers, viewsets

from apps.accounts.permissions import HasGlobalCapability
from apps.accounts.roles import Cap
from apps.customers.views import CustomerScopedMixin

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    customer_code = serializers.CharField(source="customer.code", read_only=True, default=None)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "created_at",
            "actor_label",
            "action",
            "customer",
            "customer_code",
            "target_type",
            "target_id",
            "outcome",
            "request_id",
            "metadata",
        ]
        read_only_fields = fields


def _apply_filters(qs: QuerySet[AuditEvent], params: dict) -> QuerySet[AuditEvent]:
    action = (params.get("action") or "").strip()[:64]
    if action:
        qs = qs.filter(action__startswith=action)
    outcome = params.get("outcome")
    if outcome in AuditEvent.Outcome.values:
        qs = qs.filter(outcome=outcome)
    return qs


class AuditEventViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """System-wide audit log (super admin / system.audit.read)."""

    permission_classes = [HasGlobalCapability]
    global_capability = Cap.SYSTEM_AUDIT_READ
    serializer_class = AuditEventSerializer

    def get_queryset(self) -> QuerySet[AuditEvent]:
        return _apply_filters(AuditEvent.objects.select_related("customer"), self.request.query_params)


class CustomerAuditEventViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    customer_capability = Cap.CUSTOMER_AUDIT_READ
    serializer_class = AuditEventSerializer

    def get_queryset(self) -> QuerySet[AuditEvent]:
        if getattr(self, "swagger_fake_view", False):
            return AuditEvent.objects.none()
        qs = AuditEvent.objects.filter(customer=self.get_customer()).select_related("customer")
        return _apply_filters(qs, self.request.query_params)
