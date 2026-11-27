"""Customer-scoped proposal API. Execution in VSA X (VSA5-EXEC) is a separate, gated action; see move_execution."""

from typing import Any

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.customers.views import CustomerScopedMixin

from . import move_execution, move_lists, moves
from .models import GroupMoveExecution, GroupMoveRequest


class ExecutionSerializer(serializers.ModelSerializer):
    executed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    answer = serializers.SerializerMethodField()

    def get_answer(self, obj: GroupMoveExecution) -> dict[str, Any] | None:
        """For "answered OK but not applied": the shape of VSA X's answer (content type, size, documented or not) from
        the audit event, so an administrator can tell an API answer from a proxy page without server logs. Never the
        body itself."""
        if obj.error_code != move_execution.NOT_APPLIED_ERROR:
            return None
        from apps.audit.models import AuditEvent

        event = (
            AuditEvent.objects.filter(
                customer_id=obj.customer_id,
                target_type="group_move_request",
                target_id=str(obj.proposal_id),
                action__startswith="group_move.execute_",
            )
            .exclude(action="group_move.execute_started")
            .order_by("-created_at")
            .first()
        )
        answer = (event.metadata or {}).get("answer") if event else None
        if not isinstance(answer, dict):
            return None
        return {k: answer[k] for k in ("documented_answer", "content_type", "content_length") if k in answer}

    class Meta:
        model = GroupMoveExecution
        fields = [
            "state",
            "executed_by",
            "started_at",
            "finished_at",
            "http_status",
            "error_code",
            "observed_group_id",
            "verified_at",
            "answer",
        ]
        read_only_fields = fields


class MoveSerializer(serializers.ModelSerializer):
    requested_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    target_group_name = serializers.CharField(source="target_group.name")
    target_group_external_id = serializers.CharField(source="target_group.external_id")
    expired = serializers.SerializerMethodField()
    execution_enabled = serializers.SerializerMethodField()
    execution_available = serializers.SerializerMethodField()
    execution_unavailable_reason = serializers.SerializerMethodField()
    self_approval_allowed = serializers.SerializerMethodField()
    execution_blocked_reason = serializers.SerializerMethodField()
    execution = serializers.SerializerMethodField()

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
            "execution_available",
            "execution_unavailable_reason",
            "self_approval_allowed",
            "execution_blocked_reason",
            "execution",
        ]
        read_only_fields = fields

    def get_expired(self, obj: GroupMoveRequest) -> bool:
        return obj.expires_at <= timezone.now()

    def get_execution_enabled(self, obj: GroupMoveRequest) -> bool:
        return move_execution.execution_status(obj)[0]

    def get_self_approval_allowed(self, obj: GroupMoveRequest) -> bool:
        """The requester may approve and execute their own proposal (REQUIRE_SECOND_APPROVER is off)."""
        return not settings.CATALOG_REQUIRE_SEPARATE_REVIEWER

    def get_execution_unavailable_reason(self, obj: GroupMoveRequest) -> str:
        """Why moving is not set up for the integration (empty when it is): server stop, switch or token."""
        return move_execution.availability(obj.asset.integration_instance)[1]

    def get_execution_available(self, obj: GroupMoveRequest) -> bool:
        """Execution is set up for the integration (switches + token), whatever this proposal's state."""
        return move_execution.availability(obj.asset.integration_instance)[0]

    def get_execution_blocked_reason(self, obj: GroupMoveRequest) -> str:
        return move_execution.execution_status(obj)[1]

    @extend_schema_field(ExecutionSerializer(allow_null=True))
    def get_execution(self, obj: GroupMoveRequest) -> dict[str, Any] | None:
        execution = getattr(obj, "execution", None)
        return ExecutionSerializer(execution).data if execution else None


class ProposalInput(serializers.Serializer):
    asset = serializers.UUIDField()
    target_group = serializers.UUIDField()
    reason = serializers.CharField(min_length=10, max_length=1000)


class MoveNowInput(serializers.Serializer):
    asset = serializers.UUIDField()
    target_group = serializers.UUIDField()
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class ReviewInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    # Optional since 2026-11-24 (one step for administrators); a default note is recorded in the audit log.
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


REVIEW_DEFAULT = {"approved": "Approved by an administrator.", "rejected": "Rejected by an administrator."}


class GroupMoveViewSet(CustomerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = MoveSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_customer(self) -> Any:
        self.customer_capability = {
            "create": Cap.CUSTOMER_PROPOSE_MOVE,
            "review": Cap.CUSTOMER_APPROVE_MOVE,
            "execute": Cap.CUSTOMER_APPROVE_MOVE,
            "verify": Cap.CUSTOMER_APPROVE_MOVE,
            "move_now": Cap.CUSTOMER_APPROVE_MOVE,
            "check_list": Cap.CUSTOMER_PROPOSE_MOVE,
        }.get(self.action, Cap.CUSTOMER_READ)
        return super().get_customer()

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return GroupMoveRequest.objects.none()
        qs = GroupMoveRequest.objects.filter(customer=self.get_customer()).select_related(
            "requested_by", "reviewed_by", "target_group", "asset__integration_instance", "execution__executed_by"
        )
        if self.action == "list":
            view = self.request.query_params.get("view", "")
            if view == "waiting":  # needs a decision: pending and not expired
                qs = qs.filter(state="pending", expires_at__gt=timezone.now())
            elif view == "to_move":  # approved, not sent yet
                qs = qs.filter(
                    Q(execution__isnull=True)
                    | Q(execution__state="failed", execution__error_code__in=move_execution.RETRYABLE_ERRORS),
                    state="approved",
                )
            elif view == "to_verify":  # sent, but VSA X has not confirmed the new group yet
                qs = qs.filter(execution__state__in=move_execution.VERIFIABLE)
        return qs

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

    @extend_schema(request=MoveNowInput, responses={200: MoveSerializer})
    @action(detail=False, methods=["post"], url_path="move-now")
    def move_now(self, request: Any, **kwargs: Any) -> Response:
        """Administrators: move one device in VSA X now (record, approve, send, read back) in a single step."""
        customer = self.get_customer()
        data = MoveNowInput(data=request.data)
        data.is_valid(raise_exception=True)
        proposal = moves.move_now(
            customer,
            request.user,
            data.validated_data["asset"],
            data.validated_data["target_group"],
            data.validated_data["reason"],
            request,
        )
        return Response(MoveSerializer(self.get_queryset().get(pk=proposal.pk)).data)

    @extend_schema(request=ReviewInput, responses={200: MoveSerializer})
    @action(detail=True, methods=["post"])
    def review(self, request: Any, pk: str | None = None, **kwargs: Any) -> Response:
        customer = self.get_customer()
        original = self.get_object()  # scoped lookup before input validation
        data = ReviewInput(data=request.data)
        data.is_valid(raise_exception=True)
        decision = data.validated_data["decision"]
        reason = data.validated_data["reason"].strip() or REVIEW_DEFAULT[decision]
        proposal = moves.review(customer, request.user, original.id, decision, reason, request)
        return Response(MoveSerializer(proposal).data)

    @extend_schema(request=None, responses={200: MoveSerializer})
    @action(detail=True, methods=["post"])
    def execute(self, request: Any, pk: str | None = None, **kwargs: Any) -> Response:
        """Send the approved move to VSA X once (gated; see VSA5-EXEC). Re-sending is impossible; use verify."""
        customer = self.get_customer()
        original = self.get_object()
        move_execution.execute_move(customer, request.user, original.id, request)
        return Response(MoveSerializer(self.get_queryset().get(pk=original.pk)).data)

    @extend_schema(request=None, responses={200: MoveSerializer})
    @action(detail=True, methods=["post"])
    def verify(self, request: Any, pk: str | None = None, **kwargs: Any) -> Response:
        """Read the device back from VSA X (GET) to confirm an unknown/unconfirmed execution."""
        customer = self.get_customer()
        original = self.get_object()
        move_execution.verify(customer, request.user, original.id, request)
        return Response(MoveSerializer(self.get_queryset().get(pk=original.pk)).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def destinations(self, request: Any, **kwargs: Any) -> Response:
        """MOV-02: active groups of the current inventory (the "Move to" choices for a device list)."""
        return Response({"groups": move_lists.destinations(self.get_customer().id)})

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="check-list")
    def check_list(self, request: Any, **kwargs: Any) -> Response:
        """MOV-02: JSON ``{text, target_group}`` or multipart ``file`` + ``target_group``. Matches every line and says
        whether it would be moved or why it is skipped (not in VSA X, already there, ...). Records and sends nothing."""
        customer = self.get_customer()
        try:
            target = serializers.UUIDField().run_validation(request.data.get("target_group"))
        except serializers.ValidationError as exc:
            raise ValidationError({"target_group": "Choose the group to move the devices to."}) from exc
        records = move_lists.records_from(request.data, request.FILES)
        return Response(move_lists.check(customer, request.user, target, records))

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
        from .group_suggestions import suggestions

        hints = suggestions(observation)
        return Response(
            {
                **hints,
                "asset": str(observation.asset_id),
                "source_group": observation.group_name,
                "policy_impact": moves.POLICY_IMPACT,
                "execution_enabled": move_execution.availability(observation.asset.integration_instance)[0],
                "execution_unavailable_reason": move_execution.availability(observation.asset.integration_instance)[1],
                # One step (product owner, 2026-11-24): administrators move directly unless a second approver is
                # required on this server.
                "move_now_allowed": (
                    not settings.CATALOG_REQUIRE_SEPARATE_REVIEWER
                    and scope.has_customer_capability(request.user, customer.id, Cap.CUSTOMER_APPROVE_MOVE)
                    and move_execution.availability(observation.asset.integration_instance)[0]
                ),
                "groups": [
                    {"id": str(g.id), "external_id": g.external_id, "name": g.name, "site": g.site_external_id}
                    for g in groups
                ],
            }
        )
