"""Customer-scoped proposal API. There is deliberately no execute action or vendor write client."""

from typing import Any

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.customers.views import CustomerScopedMixin

from . import moves
from .models import GroupMoveRequest


class MoveSerializer(serializers.ModelSerializer):
    requested_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    target_group_name = serializers.CharField(source="target_group.name")
    target_group_external_id = serializers.CharField(source="target_group.external_id")
    expired = serializers.SerializerMethodField()
    execution_enabled = serializers.SerializerMethodField()

    class Meta:
        model = GroupMoveRequest
        fields = [
            "id",
            "asset",
            "generation",
            "device_name",
            "source_group_id",
            "source_group_name",
            "target_group",
            "target_group_name",
            "target_group_external_id",
            "reason",
            "policy_impact",
            "state",
            "requested_by",
            "reviewed_by",
            "review_reason",
            "created_at",
            "expires_at",
            "reviewed_at",
            "expired",
            "execution_enabled",
        ]
        read_only_fields = fields

    def get_expired(self, obj: GroupMoveRequest) -> bool:
        return obj.expires_at <= timezone.now()

    def get_execution_enabled(self, obj: GroupMoveRequest) -> bool:
        return False


class ProposalInput(serializers.Serializer):
    asset = serializers.UUIDField()
    target_group = serializers.UUIDField()
    reason = serializers.CharField(min_length=10, max_length=1000)


class ReviewInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    reason = serializers.CharField(min_length=10, max_length=1000)


class GroupMoveViewSet(CustomerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = MoveSerializer

    def get_customer(self) -> Any:
        self.customer_capability = {
            "create": Cap.CUSTOMER_PROPOSE_MOVE,
            "review": Cap.CUSTOMER_APPROVE_MOVE,
        }.get(self.action, Cap.CUSTOMER_READ)
        return super().get_customer()

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return GroupMoveRequest.objects.none()
        return GroupMoveRequest.objects.filter(customer=self.get_customer()).select_related(
            "requested_by", "reviewed_by", "target_group"
        )

    @extend_schema(request=ProposalInput, responses={201: MoveSerializer})
    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        data = ProposalInput(data=request.data)
        data.is_valid(raise_exception=True)
        proposal = moves.propose(
            customer,
            request.user,
            data.validated_data["asset"],
            data.validated_data["target_group"],
            data.validated_data["reason"],
            request,
        )
        return Response(MoveSerializer(proposal).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=ReviewInput, responses={200: MoveSerializer})
    @action(detail=True, methods=["post"])
    def review(self, request: Any, pk: str | None = None, **kwargs: Any) -> Response:
        customer = self.get_customer()
        original = self.get_object()  # scoped lookup before input validation
        data = ReviewInput(data=request.data)
        data.is_valid(raise_exception=True)
        proposal = moves.review(
            customer, request.user, original.id, data.validated_data["decision"], data.validated_data["reason"], request
        )
        return Response(MoveSerializer(proposal).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def options(self, request: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        field = serializers.UUIDField()
        try:
            asset_id = field.run_validation(request.query_params.get("asset"))
        except serializers.ValidationError as exc:
            raise ValidationError({"asset": "Provide a device UUID."}) from exc
        observation, groups = moves.options(customer.id, asset_id)
        return Response(
            {
                "asset": str(observation.asset_id),
                "source_group": observation.group_name,
                "policy_impact": moves.POLICY_IMPACT,
                "execution_enabled": False,
                "groups": [
                    {"id": str(g.id), "external_id": g.external_id, "name": g.name, "site": g.site_external_id}
                    for g in groups
                ],
            }
        )
