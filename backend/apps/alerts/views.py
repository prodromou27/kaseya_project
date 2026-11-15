"""``/alert-subscriptions/`` (my watches) and ``/alerts/`` (my alerts). Always the requesting user's own rows."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.models import Customer

from . import engine
from .models import Alert, AlertSubscription


def _readable_customer_ids(user: Any) -> set[Any]:
    return set(
        scope.scope_queryset(Customer.objects.all(), user, Cap.CUSTOMER_READ, "self").values_list("id", flat=True)
    )


class SubscriptionSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    label = serializers.SerializerMethodField()

    class Meta:
        model = AlertSubscription
        fields = ["id", "customer", "customer_code", "kind", "params", "enabled", "label", "created_at"]
        read_only_fields = ["id", "customer_code", "label", "created_at"]

    def get_label(self, obj: AlertSubscription) -> str:
        return engine.describe(obj.kind, obj.params)

    def validate_customer(self, value: Customer) -> Customer:
        user = self.context["request"].user
        if not scope.has_customer_capability(user, value.id, Cap.CUSTOMER_READ):
            raise serializers.ValidationError("Customer not found.")  # no existence oracle
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        kind = attrs.get("kind", getattr(self.instance, "kind", ""))
        attrs["params"] = engine.clean_params(kind, attrs.get("params", getattr(self.instance, "params", {})))
        customer = attrs.get("customer", getattr(self.instance, "customer", None))
        same = AlertSubscription.objects.filter(
            user=self.context["request"].user, customer=customer, kind=kind, params=attrs["params"]
        )
        if self.instance is not None:
            same = same.exclude(pk=self.instance.pk)
        if same.exists():
            raise serializers.ValidationError("You already have this watch for this customer.")
        return attrs


class AlertSubscriptionViewSet(viewsets.ModelViewSet):
    serializer_class = SubscriptionSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    pagination_class = None

    def get_queryset(self) -> QuerySet[AlertSubscription]:
        if getattr(self, "swagger_fake_view", False):
            return AlertSubscription.objects.none()
        return AlertSubscription.objects.filter(
            user=self.request.user, customer_id__in=_readable_customer_ids(self.request.user)
        ).select_related("customer")

    def perform_create(self, serializer: SubscriptionSerializer) -> None:
        sub = serializer.save(user=self.request.user)
        engine_prime(sub)
        record_event(
            action="alert_subscription.created",
            outcome="success",
            actor=self.request.user,
            customer=sub.customer,
            target_type="alert_subscription",
            target_id=str(sub.id),
            request=self.request,
            metadata={"kind": sub.kind},
        )

    def perform_update(self, serializer: SubscriptionSerializer) -> None:
        sub = serializer.save(state=None)  # parameters changed: re-prime, never alert on the old state
        engine_prime(sub)


def engine_prime(sub: AlertSubscription) -> None:
    """Record the starting state now so the next sync only reports what changed."""
    try:
        current, _ = engine._matches(sub, {})
    except Exception:
        return
    sub.state = sorted(current)
    sub.save(update_fields=["state"])


class AlertSerializer(serializers.ModelSerializer):
    customer_code = serializers.CharField(source="customer.code", read_only=True)

    class Meta:
        model = Alert
        fields = ["id", "customer", "customer_code", "kind", "title", "body", "link", "created_at", "read_at"]
        read_only_fields = fields


class AlertViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AlertSerializer

    def get_queryset(self) -> QuerySet[Alert]:
        if getattr(self, "swagger_fake_view", False):
            return Alert.objects.none()
        qs = Alert.objects.filter(
            user=self.request.user, customer_id__in=_readable_customer_ids(self.request.user)
        ).select_related("customer")
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(read_at__isnull=True)
        return qs

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request: Request) -> Response:
        return Response({"unread": self.get_queryset().filter(read_at__isnull=True).count()})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def read(self, request: Request, pk: str | None = None) -> Response:
        self.get_queryset().filter(pk=pk, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"ok": True})

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request: Request) -> Response:
        n = self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"marked": n})
