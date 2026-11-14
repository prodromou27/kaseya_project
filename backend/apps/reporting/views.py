from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from .models import ReportDefinition, ReportRun, ReportSchedule, SavedView
from .registry import REPORT_TYPES, validate_filters
from .renderers import CONTENT_TYPES
from .scheduling import compute_next_run, inbox_runs, user_may_receive, validate_timezone
from .services import request_report, storage_path, user_may_access_report

# ---------------------------------------------------------------------------------------------- runs


class ReportRunSerializer(serializers.ModelSerializer):
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    requested_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    download_available = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()

    class Meta:
        model = ReportRun
        fields = [
            "id",
            "customer",
            "customer_code",
            "requested_by",
            "report_type",
            "title",
            "format",
            "filters",
            "state",
            "row_count",
            "data_basis",
            "as_of_generation_ids",
            "regenerated_from",
            "error_code",
            "created_at",
            "started_at",
            "completed_at",
            "download_available",
        ]
        read_only_fields = fields

    def get_title(self, obj: ReportRun) -> str:
        rt = REPORT_TYPES.get(obj.report_type)
        return rt.title if rt else obj.report_type

    def get_download_available(self, obj: ReportRun) -> bool:
        artifact = getattr(obj, "artifact", None)
        return bool(
            obj.state == ReportRun.State.COMPLETED
            and artifact
            and not artifact.purged_at
            and artifact.expires_at > timezone.now()
        )


class ReportRequestSerializer(serializers.Serializer):
    report_type = serializers.ChoiceField(choices=sorted(REPORT_TYPES))
    format = serializers.ChoiceField(choices=["csv", "xlsx", "pdf"], default="csv")
    filters = serializers.DictField(required=False, default=dict)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        report_type = REPORT_TYPES[attrs["report_type"]]
        if attrs["format"] not in report_type.formats:
            raise ValidationError({"format": f"Supported: {', '.join(report_type.formats)}"})
        attrs["filters"] = validate_filters(report_type, self.context["customer"], attrs.get("filters") or {})
        return attrs


def _require_report_caps(user: Any, customer: Any, report_type_key: str) -> None:
    if not user_may_access_report(user, ReportRun(customer=customer, report_type=report_type_key)):
        raise PermissionDenied("You do not have the capabilities required for this report type.")


class CustomerReportViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    customer_capability = Cap.CUSTOMER_EXPORT
    serializer_class = ReportRunSerializer

    def get_queryset(self) -> QuerySet[ReportRun]:
        if getattr(self, "swagger_fake_view", False):
            return ReportRun.objects.none()
        customer, user = self.get_customer(), self.request.user
        allowed = [k for k in REPORT_TYPES if user_may_access_report(user, ReportRun(customer=customer, report_type=k))]
        return ReportRun.objects.filter(customer=customer, report_type__in=allowed).select_related(
            "customer", "requested_by", "artifact"
        )

    @extend_schema(request=ReportRequestSerializer, responses={202: ReportRunSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        body = ReportRequestSerializer(data=request.data, context={"customer": customer})
        body.is_valid(raise_exception=True)
        _require_report_caps(request.user, customer, body.validated_data["report_type"])
        run = request_report(
            request.user,
            customer,
            body.validated_data["report_type"],
            body.validated_data["format"],
            body.validated_data["filters"],
            request,
        )
        run.refresh_from_db()
        return Response(ReportRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


class ReportRunViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Object routes by report ID. The customer is resolved from the run row, then re-authorised."""

    serializer_class = ReportRunSerializer
    queryset = ReportRun.objects.none()

    def get_object(self) -> ReportRun:
        run = (
            ReportRun.objects.select_related("customer", "requested_by")
            .filter(pk=_uuid_or_none(self.kwargs["pk"]))
            .first()
        )
        if run is None or not user_may_access_report(self.request.user, run):
            record_event(
                action="authz.denied",
                outcome="denied",
                actor=self.request.user,
                target_type="report_run",
                target_id=str(self.kwargs["pk"])[:64],
                request=self.request,
            )
            raise NotFound()
        return run

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> FileResponse:
        run = self.get_object()  # fresh authorisation on every download
        artifact = getattr(run, "artifact", None)
        if (
            run.state != ReportRun.State.COMPLETED
            or artifact is None
            or artifact.purged_at is not None
            or artifact.expires_at <= timezone.now()
        ):
            raise NotFound("Report artifact is not available (pending, failed or expired).")
        path = storage_path(artifact.storage_key)
        if not path.is_file():
            raise NotFound("Report artifact is not available.")
        record_event(
            action="report.downloaded",
            outcome="success",
            actor=request.user,
            customer=run.customer,
            target_type="report_run",
            target_id=str(run.id),
            request=request,
            metadata={"sha256": artifact.sha256, "bytes": artifact.bytes, "format": artifact.format},
        )
        filename = f"{run.customer.code}_{run.report_type}_{run.created_at:%Y%m%dT%H%M%SZ}.{artifact.format}"
        response = FileResponse(
            path.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type=CONTENT_TYPES.get(artifact.format, "application/octet-stream"),
        )
        response["X-Content-SHA256"] = artifact.sha256
        return response

    @extend_schema(request=None, responses={202: ReportRunSerializer})
    @action(detail=True, methods=["post"])
    def regenerate(self, request: Request, pk: str | None = None) -> Response:
        """Re-create the file from the run's *pinned* snapshot (P2-06). Requires the same capabilities."""
        original = self.get_object()
        rt = REPORT_TYPES.get(original.report_type)
        if rt is None or rt.pin is None or not original.as_of_generation_ids:
            raise ValidationError({"detail": "Only completed snapshot reports can be regenerated."})
        run = request_report(
            request.user,
            original.customer,
            original.report_type,
            original.format,
            original.filters,
            request,
            regenerated_from=original,
        )
        run.refresh_from_db()
        return Response(ReportRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses={200: ReportRunSerializer(many=True)})
    @action(detail=False, methods=["get"])
    def inbox(self, request: Request) -> Response:
        """Scheduled reports delivered to me (in-portal delivery), filtered by *current* authorisation."""
        return Response(ReportRunSerializer(inbox_runs(request.user), many=True).data)


class ReportTemplatesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        out = []
        for rt in REPORT_TYPES.values():
            fields = {}
            for name, f in rt.filter_serializer().fields.items():
                info: dict[str, Any] = {"type": type(f).__name__, "required": f.required}
                if hasattr(f, "choices") and isinstance(f.choices, dict):
                    info["choices"] = list(f.choices)
                fields[name] = info
            out.append(
                {
                    "key": rt.key,
                    "title": rt.title,
                    "description": rt.description,
                    "formats": list(rt.formats),
                    "required_capabilities": sorted(rt.required_capabilities),
                    "columns": list(rt.columns),
                    "filters": fields,
                    "limitations": rt.limitations,
                }
            )
        return Response(out)


# ---------------------------------------------------------------------------------------------- saved views

VIEW_FILTERS: dict[str, dict[str, str]] = {
    "assets": {
        "search": "str",
        "group": "str",
        "os": "str",
        "offline": "bool_str",
        "ordering": "str",
        "device_type": "str",
        "site": "str",
        "software_status": "str",
        "group_id": "str",
        "organization": "str",
        "instance": "uuid",
        "offline_days": "str",
    },
    "software": {"state": "str", "product": "uuid", "search": "str", "asset": "uuid"},
    "os_updates": {"state": "str", "severity": "str", "kb": "str", "asset": "uuid"},
}


class SavedViewSerializer(serializers.ModelSerializer):
    owner = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = SavedView
        fields = ["id", "name", "view_type", "filters", "shared", "owner", "created_at", "updated_at"]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        from apps.inventory.models import Asset

        view_type = attrs.get("view_type") or getattr(self.instance, "view_type", None)
        filters = attrs.get("filters", getattr(self.instance, "filters", {})) or {}
        if not isinstance(filters, dict):
            raise ValidationError({"filters": "Must be an object."})
        allowed = VIEW_FILTERS.get(view_type or "", {})
        unknown = set(filters) - set(allowed)
        if unknown:
            raise ValidationError({"filters": f"Unknown filter keys: {', '.join(sorted(unknown))}"})
        if view_type == "assets":
            from apps.inventory.filters import AssetFilters

            serializer = AssetFilters(data={key: value for key, value in filters.items() if value not in (None, "")})
            serializer.is_valid(raise_exception=True)
            attrs["filters"] = {
                key: str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in serializer.validated_data.items()
            }
            return attrs
        clean: dict[str, str] = {}
        for key, value in filters.items():
            if value in (None, ""):
                continue
            if not isinstance(value, str | bool) or len(str(value)) > 255:
                raise ValidationError({"filters": f"Invalid value for {key}."})
            if allowed[key] == "uuid":
                parsed = _uuid_or_none(value)
                if parsed is None:
                    raise ValidationError({"filters": f"{key} must be a UUID."})
                if key == "asset" and not Asset.objects.filter(pk=parsed, customer=self.context["customer"]).exists():
                    raise ValidationError({"filters": "Asset not found for this customer."})
            clean[key] = str(value)
        attrs["filters"] = clean
        return attrs


class CustomerSavedViewViewSet(CustomerScopedMixin, viewsets.ModelViewSet):
    customer_capability = Cap.CUSTOMER_READ
    serializer_class = SavedViewSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self) -> QuerySet[SavedView]:
        if getattr(self, "swagger_fake_view", False):
            return SavedView.objects.none()
        qs = (
            SavedView.objects.filter(customer=self.get_customer())
            .filter(Q(owner=self.request.user) | Q(shared=True))
            .select_related("owner")
        )
        vt = self.request.query_params.get("view_type")
        return qs.filter(view_type=vt) if vt in SavedView.ViewType.values else qs

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if "customer_pk" in self.kwargs and not getattr(self, "swagger_fake_view", False):
            ctx["customer"] = self.get_customer()
        return ctx

    def perform_create(self, serializer: SavedViewSerializer) -> None:
        serializer.save(customer=self.get_customer(), owner=self.request.user)

    def _owned(self, obj: SavedView) -> None:
        if obj.owner_id != self.request.user.pk:
            raise PermissionDenied("Only the owner can change this saved view.")

    def perform_update(self, serializer: SavedViewSerializer) -> None:
        self._owned(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance: SavedView) -> None:
        self._owned(instance)
        instance.delete()


# ---------------------------------------------------------------------------------------------- definitions & schedules


class ReportDefinitionSerializer(serializers.ModelSerializer):
    owner = serializers.SlugRelatedField(slug_field="email", read_only=True)
    report_type = serializers.ChoiceField(choices=sorted(REPORT_TYPES))
    format = serializers.ChoiceField(choices=["csv", "xlsx", "pdf"], default="csv")

    class Meta:
        model = ReportDefinition
        fields = ["id", "name", "report_type", "format", "filters", "owner", "created_at", "updated_at"]
        read_only_fields = ["id", "owner", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        rt = REPORT_TYPES[attrs.get("report_type") or self.instance.report_type]
        fmt = attrs.get("format") or getattr(self.instance, "format", "csv")
        if fmt not in rt.formats:
            raise ValidationError({"format": f"Supported: {', '.join(rt.formats)}"})
        attrs["filters"] = validate_filters(rt, self.context["customer"], attrs.get("filters", {}) or {})
        _require_report_caps(self.context["request"].user, self.context["customer"], rt.key)
        return attrs


class _OwnedCustomerViewSet(CustomerScopedMixin, viewsets.ModelViewSet):
    customer_capability = Cap.CUSTOMER_EXPORT
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if "customer_pk" in self.kwargs and not getattr(self, "swagger_fake_view", False):
            ctx["customer"] = self.get_customer()
        return ctx


class CustomerReportDefinitionViewSet(_OwnedCustomerViewSet):
    serializer_class = ReportDefinitionSerializer

    def get_queryset(self) -> QuerySet[ReportDefinition]:
        if getattr(self, "swagger_fake_view", False):
            return ReportDefinition.objects.none()
        return ReportDefinition.objects.filter(customer=self.get_customer(), owner=self.request.user)

    def perform_create(self, serializer: ReportDefinitionSerializer) -> None:
        d = serializer.save(customer=self.get_customer(), owner=self.request.user)
        record_event(
            action="report.definition_created",
            outcome="success",
            actor=self.request.user,
            customer=d.customer,
            target_type="report_definition",
            target_id=str(d.id),
            request=self.request,
        )

    def perform_destroy(self, instance: ReportDefinition) -> None:
        if instance.schedules.exists():
            raise ValidationError({"detail": "Delete the schedules first."})
        instance.delete()


class ReportScheduleSerializer(serializers.ModelSerializer):
    definition = serializers.PrimaryKeyRelatedField(queryset=ReportDefinition.objects.all())
    recipients = serializers.ListField(child=serializers.EmailField(), required=False, default=list, write_only=True)
    recipient_emails = serializers.SerializerMethodField()

    class Meta:
        model = ReportSchedule
        fields = [
            "id",
            "definition",
            "frequency",
            "time_of_day",
            "weekday",
            "day_of_month",
            "timezone",
            "recipients",
            "recipient_emails",
            "enabled",
            "next_run_at",
            "last_run_at",
            "created_at",
        ]
        read_only_fields = ["id", "next_run_at", "last_run_at", "created_at", "recipient_emails"]

    def get_recipient_emails(self, obj: ReportSchedule) -> list[str]:
        return sorted(u.email for u in obj.recipients.all())

    def validate_definition(self, value: ReportDefinition) -> ReportDefinition:
        request = self.context["request"]
        if value.customer_id != self.context["customer"].id or value.owner_id != request.user.pk:
            raise ValidationError("Definition not found.")  # cross-customer / other users' definitions denied
        return value

    def validate_timezone(self, value: str) -> str:
        try:
            validate_timezone(value)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        freq = attrs.get("frequency") or getattr(self.instance, "frequency", None)
        weekday = attrs.get("weekday", getattr(self.instance, "weekday", None))
        dom = attrs.get("day_of_month", getattr(self.instance, "day_of_month", None))
        if freq == "weekly" and (weekday is None or not 0 <= weekday <= 6):
            raise ValidationError({"weekday": "Weekly schedules need weekday 0-6 (Monday=0)."})
        if freq == "monthly" and (dom is None or not 1 <= dom <= 28):
            raise ValidationError({"day_of_month": "Monthly schedules need day_of_month 1-28."})
        if "recipients" in attrs:
            users = []
            for email in attrs["recipients"]:
                user = User.objects.filter(email__iexact=email, is_active=True).first()
                definition = attrs.get("definition") or self.instance.definition
                probe = ReportSchedule(definition=definition)
                if user is None or not user_may_receive(user, probe):
                    raise ValidationError({"recipients": f"{email} cannot receive this customer's report."})
                users.append(user)
            attrs["recipients"] = users
        return attrs


class CustomerReportScheduleViewSet(_OwnedCustomerViewSet):
    serializer_class = ReportScheduleSerializer

    def get_queryset(self) -> QuerySet[ReportSchedule]:
        if getattr(self, "swagger_fake_view", False):
            return ReportSchedule.objects.none()
        return (
            ReportSchedule.objects.filter(definition__customer=self.get_customer(), definition__owner=self.request.user)
            .select_related("definition")
            .prefetch_related("recipients")
        )

    def _save(self, serializer: ReportScheduleSerializer, **extra: Any) -> ReportSchedule:
        recipients = serializer.validated_data.pop("recipients", None)
        with transaction.atomic():
            schedule = serializer.save(**extra)
            if recipients is not None:
                schedule.recipients.set(recipients)
            schedule.next_run_at = compute_next_run(schedule, timezone.now()) if schedule.enabled else None
            schedule.save(update_fields=["next_run_at"])
        record_event(
            action="report.schedule_saved",
            outcome="success",
            actor=self.request.user,
            customer=schedule.definition.customer,
            target_type="report_schedule",
            target_id=str(schedule.id),
            request=self.request,
            metadata={
                "frequency": schedule.frequency,
                "timezone": schedule.timezone,
                "recipients": [u.email for u in schedule.recipients.all()],
            },
        )
        return schedule

    def perform_create(self, serializer: ReportScheduleSerializer) -> None:
        self._save(serializer, created_by=self.request.user)

    def perform_update(self, serializer: ReportScheduleSerializer) -> None:
        self._save(serializer)

    def perform_destroy(self, instance: ReportSchedule) -> None:
        if instance.executions.exists():
            instance.enabled, instance.next_run_at = False, None  # keep execution history
            instance.save(update_fields=["enabled", "next_run_at"])
        else:
            instance.recipients.clear()
            instance.delete()


class CustomerTrendViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    """``/customers/{id}/trends/?days=90`` — history from retained generations (P2-06)."""

    customer_capability = Cap.CUSTOMER_READ
    queryset = ReportRun.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from .trends import trend_points

        try:
            days = max(1, min(int(request.query_params.get("days", "90")), 730))
        except ValueError as exc:
            raise ValidationError({"days": "Integer 1-730."}) from exc
        return Response(trend_points(self.get_customer().id, days))
