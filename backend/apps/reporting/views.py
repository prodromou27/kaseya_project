from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from .models import ReportRun
from .registry import REPORT_TYPES
from .services import request_report, storage_path, user_may_access_report


class ReportRunSerializer(serializers.ModelSerializer):
    customer_code = serializers.CharField(source="customer.code", read_only=True)
    requested_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    download_available = serializers.SerializerMethodField()

    class Meta:
        model = ReportRun
        fields = [
            "id",
            "customer",
            "customer_code",
            "requested_by",
            "report_type",
            "format",
            "filters",
            "state",
            "row_count",
            "data_basis",
            "error_code",
            "created_at",
            "started_at",
            "completed_at",
            "download_available",
        ]
        read_only_fields = fields

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
    format = serializers.CharField(default="csv", max_length=8)
    filters = serializers.DictField(required=False, default=dict)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        report_type = REPORT_TYPES[attrs["report_type"]]
        if attrs["format"] not in report_type.formats:
            raise ValidationError({"format": f"Supported: {', '.join(report_type.formats)}"})
        filters = report_type.filter_serializer(data=attrs.get("filters") or {})
        filters.is_valid(raise_exception=True)
        unknown = set(attrs.get("filters") or {}) - set(filters.fields)
        if unknown:
            raise ValidationError({"filters": f"Unknown filter keys: {', '.join(sorted(unknown))}"})
        attrs["filters"] = {
            k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in filters.validated_data.items()
        }
        return attrs


class CustomerReportViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    customer_capability = Cap.CUSTOMER_EXPORT
    serializer_class = ReportRunSerializer

    def get_queryset(self) -> QuerySet[ReportRun]:
        if getattr(self, "swagger_fake_view", False):
            return ReportRun.objects.none()
        runs = ReportRun.objects.filter(customer=self.get_customer()).select_related(
            "customer", "requested_by", "artifact"
        )
        customer, user = self.get_customer(), self.request.user
        allowed = [k for k in REPORT_TYPES if user_may_access_report(user, ReportRun(customer=customer, report_type=k))]
        return runs.filter(report_type__in=allowed)

    @extend_schema(request=ReportRequestSerializer, responses={202: ReportRunSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        body = ReportRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        probe = ReportRun(customer=customer, report_type=body.validated_data["report_type"])
        if not user_may_access_report(request.user, probe):
            raise PermissionDenied("You do not have the capabilities required for this report type.")
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


class ReportRunViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Object routes by report ID. The customer is resolved from the run row, then re-authorised."""

    serializer_class = ReportRunSerializer

    def get_queryset(self) -> QuerySet[ReportRun]:
        return scope.scope_queryset(
            ReportRun.objects.select_related("customer", "requested_by", "artifact"),
            self.request.user,
            Cap.CUSTOMER_EXPORT,
        )

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

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.BINARY})
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
            metadata={"sha256": artifact.sha256, "bytes": artifact.bytes},
        )
        filename = f"{run.customer.code}_{run.report_type}_{run.created_at:%Y%m%dT%H%M%SZ}.{artifact.format}"
        response = FileResponse(path.open("rb"), as_attachment=True, filename=filename, content_type="text/csv")
        response["X-Content-SHA256"] = artifact.sha256
        return response


def _uuid_or_none(value: Any) -> Any:
    import uuid

    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
