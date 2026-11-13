"""VSA2 onboarding reconciliation API. Customer always comes from the URL + policy, never from the body.

Capabilities: view = ``customer.read``; upload/compare/review = ``customer.sync``; workbook/CSV = ``customer.export``.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin
from apps.inventory.queries import current_generations
from apps.reporting.renderers import CONTENT_TYPES

from . import importer, services, workbook
from .models import ExpectedInventoryUpload, MappingTemplate, ReconciliationResult, ReconciliationRun

PREVIEW_ROWS = 20


class Rejected(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "rejected"


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "blocked"


def _rejected(exc: importer.ImportRejected) -> Rejected:
    return Rejected(exc.message, exc.code)


def _uuid_or_404(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise NotFound() from exc


class ActionCapabilityMixin(CustomerScopedMixin):
    write_actions: frozenset[str] = frozenset({"create", "destroy", "preview", "review"})
    export_actions: frozenset[str] = frozenset({"export"})
    action: str | None

    def get_customer(self) -> Any:
        if self.action in self.export_actions:
            self.customer_capability = Cap.CUSTOMER_EXPORT
        elif self.action in self.write_actions:
            self.customer_capability = Cap.CUSTOMER_SYNC
        return super().get_customer()


# ---------------------------------------------------------------------------------------------- uploads


class OnboardingUploadSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    available = serializers.SerializerMethodField()

    class Meta:
        model = ExpectedInventoryUpload
        fields = [
            "id",
            "display_name",
            "file_format",
            "sha256",
            "bytes",
            "sheets",
            "uploaded_by",
            "created_at",
            "expires_at",
            "purged_at",
            "available",
        ]
        read_only_fields = fields

    def get_available(self, obj: ExpectedInventoryUpload) -> bool:
        return obj.purged_at is None and obj.expires_at > timezone.now()


class OnboardingPreviewRequestSerializer(serializers.Serializer):
    sheet = serializers.CharField(max_length=64)
    header_row = serializers.IntegerField(min_value=1, max_value=importer.MAX_HEADER_ROW, default=1)
    mapping = serializers.DictField(child=serializers.IntegerField(allow_null=True), required=False)


class UploadViewSet(ActionCapabilityMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = OnboardingUploadSerializer
    parser_classes = [MultiPartParser, JSONParser]

    def get_queryset(self) -> QuerySet[ExpectedInventoryUpload]:
        if getattr(self, "swagger_fake_view", False):
            return ExpectedInventoryUpload.objects.none()
        return ExpectedInventoryUpload.objects.filter(customer=self.get_customer()).select_related("uploaded_by")

    def get_object(self) -> ExpectedInventoryUpload:
        obj = self.get_queryset().filter(pk=_uuid_or_404(self.kwargs["pk"])).first()
        if obj is None:
            raise NotFound()
        return obj

    @extend_schema(
        request={
            "multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}
        },
        responses={201: OnboardingUploadSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        f = request.FILES.get("file")
        if f is None:
            raise Rejected("Attach a .xlsx or .csv file as 'file'.", "file_required")
        from django.conf import settings

        if f.size is not None and f.size > settings.ONBOARDING_MAX_UPLOAD_BYTES:
            raise Rejected("The file exceeds the upload size limit.", "file_too_large")
        try:
            upload = services.store_upload(request.user, customer, f.name or "", f.read(), request)
        except importer.ImportRejected as exc:
            record_event(
                action="onboarding.upload",
                outcome="denied",
                actor=request.user,
                customer=customer,
                target_type="onboarding_upload",
                request=request,
                metadata={"code": exc.code},
            )
            raise _rejected(exc) from exc
        return Response(OnboardingUploadSerializer(upload).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        upload = self.get_object()
        if upload.purged_at is None:
            services.purge_upload(upload, actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=OnboardingPreviewRequestSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"])
    def preview(self, request: Request, customer_pk: str, pk: str | None = None) -> Response:
        """Headers, suggested mapping and the first rows as plain text. Nothing is stored."""
        upload = self.get_object()
        body = OnboardingPreviewRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            ws = services.load_workbook(upload).sheet(body.validated_data["sheet"])
            header_row = body.validated_data["header_row"]
            headers = importer.headers_for(ws, header_row)
            suggested = importer.suggest_mapping(headers)
            requested = body.validated_data.get("mapping")
            mapping = importer.validate_mapping(requested, len(headers)) if requested is not None else suggested
            rows = importer.mapped_rows(ws, header_row, mapping) if mapping else []
        except importer.ImportRejected as exc:
            raise _rejected(exc) from exc
        from .matching import _identifiers

        sample = []
        problems = 0
        no_identifier = 0
        for number, values in rows:
            ids, issues = _identifiers(values)
            problems += bool(issues)
            no_identifier += not ids
            if len(sample) < PREVIEW_ROWS:
                sample.append({"row": number, "values": values, "problems": issues, "has_identifier": bool(ids)})
        return Response(
            {
                "sheet": ws.name,
                "header_row": header_row,
                "headers": headers,
                "fields": [{"key": k, "label": label} for k, (label, _) in importer.FIELDS.items()],
                "identifier_fields": list(importer.IDENTIFIER_FIELDS),
                "suggested_mapping": suggested,
                "mapping": mapping,
                "data_rows": len(rows),
                "rows_with_problems": problems,
                "rows_without_identifier": no_identifier,
                "formula_cells_ignored": ws.formula_cells,
                "truncated_cells": ws.truncated_cells,
                "sample": sample,
            }
        )


# ---------------------------------------------------------------------------------------------- templates


class MappingTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = MappingTemplate
        fields = ["id", "name", "header_row", "columns", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_columns(self, value: Any) -> dict[str, str]:
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("Map at least one field to a header.")
        clean = {}
        for k, v in value.items():
            if k not in importer.FIELDS or not isinstance(v, str) or not 0 < len(v) <= 200:
                raise serializers.ValidationError("Use portal field keys mapped to header text.")
            clean[k] = v
        return clean


class TemplateViewSet(
    ActionCapabilityMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MappingTemplateSerializer
    pagination_class = None

    def get_queryset(self) -> QuerySet[MappingTemplate]:
        if getattr(self, "swagger_fake_view", False):
            return MappingTemplate.objects.none()
        return MappingTemplate.objects.filter(customer=self.get_customer())

    def get_object(self) -> MappingTemplate:
        obj = self.get_queryset().filter(pk=_uuid_or_404(self.kwargs["pk"])).first()
        if obj is None:
            raise NotFound()
        return obj

    def perform_create(self, serializer: MappingTemplateSerializer) -> None:
        customer = self.get_customer()
        if MappingTemplate.objects.filter(customer=customer, name=serializer.validated_data["name"]).exists():
            raise ValidationError({"name": "A template with this name exists."})
        serializer.save(customer=customer, created_by=self.request.user)


# ---------------------------------------------------------------------------------------------- runs


class ReconciliationRunSerializer(serializers.ModelSerializer):
    requested_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = ReconciliationRun
        fields = [
            "id",
            "upload",
            "upload_name",
            "upload_sha256",
            "sheet",
            "header_row",
            "mapping",
            "mapping_hash",
            "logic_version",
            "parameters",
            "generation",
            "data_basis",
            "stale_source_acknowledged",
            "requested_by",
            "state",
            "error_code",
            "summary",
            "created_at",
            "started_at",
            "completed_at",
        ]
        read_only_fields = fields


class ReconciliationRunRequestSerializer(serializers.Serializer):
    upload = serializers.UUIDField()
    sheet = serializers.CharField(max_length=64)
    header_row = serializers.IntegerField(min_value=1, max_value=importer.MAX_HEADER_ROW, default=1)
    mapping = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    generation = serializers.UUIDField(required=False, allow_null=True)
    allow_stale = serializers.BooleanField(default=False)


class ReconciliationResultSerializer(serializers.ModelSerializer):
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    effective_classification = serializers.CharField(read_only=True)
    candidates = serializers.SerializerMethodField()

    class Meta:
        model = ReconciliationResult
        fields = [
            "id",
            "kind",
            "row_number",
            "input",
            "classification",
            "effective_classification",
            "flags",
            "evidence",
            "asset",
            "actual",
            "candidates",
            "pending_review_row",
            "review_state",
            "reviewed_classification",
            "reviewed_asset",
            "reviewed_by",
            "reviewed_at",
            "review_note",
        ]
        read_only_fields = fields

    def get_candidates(self, obj: ReconciliationResult) -> list[dict[str, Any]]:
        return self.context.get("candidates", {}).get(obj.pk, [])


class ReconciliationReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["match", "no_match", "confirm"])
    asset = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class RunViewSet(ActionCapabilityMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReconciliationRunSerializer

    def get_queryset(self) -> QuerySet[ReconciliationRun]:
        if getattr(self, "swagger_fake_view", False):
            return ReconciliationRun.objects.none()
        return ReconciliationRun.objects.filter(customer=self.get_customer()).select_related("requested_by")

    def get_object(self) -> ReconciliationRun:
        obj = (
            self.get_queryset()
            .select_related("customer", "generation")
            .filter(pk=_uuid_or_404(self.kwargs["pk"]))
            .first()
        )
        if obj is None:
            raise NotFound()
        return obj

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def eligibility(self, request: Request, customer_pk: str) -> Response:
        """Which snapshots can be compared now, and why not if none can (same checks as run creation)."""
        customer = self.get_customer()
        gens = [
            {
                "id": str(g.pk),
                "instance": g.integration_instance.name,
                "published_at": g.published_at,
                "data_basis": g.data_basis,
                "hierarchy_status": g.hierarchy_status,
                "row_count": g.row_count,
            }
            for g in current_generations(customer.pk).select_related("integration_instance")
        ]
        blocked = None
        stale = False
        try:
            _, stale = services.choose_generation(customer, gens[0]["id"] if len(gens) == 1 else None, True)
        except services.Blocked as exc:
            blocked = {"code": exc.code, "detail": exc.message}
        return Response({"generations": gens, "blocked": blocked, "stale": stale})

    @extend_schema(request=ReconciliationRunRequestSerializer, responses={202: ReconciliationRunSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        body = ReconciliationRunRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        upload = ExpectedInventoryUpload.objects.filter(customer=customer, pk=d["upload"]).first()
        if upload is None:
            raise ValidationError({"upload": "Unknown upload."})
        try:
            run = services.request_run(
                request.user,
                customer,
                upload,
                sheet=d["sheet"],
                header_row=d["header_row"],
                mapping=d["mapping"],
                generation_id=d.get("generation"),
                allow_stale=d["allow_stale"],
                request=request,
            )
        except services.Blocked as exc:
            raise Conflict(exc.message, exc.code) from exc
        except importer.ImportRejected as exc:
            raise _rejected(exc) from exc
        run.refresh_from_db()
        return Response(ReconciliationRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, enum=["expected", "unexpected"]),
            OpenApiParameter("classification", str),
            OpenApiParameter("flag", str),
            OpenApiParameter("review_state", str, enum=["pending", "decided", "not_required"]),
        ],
        responses={200: ReconciliationResultSerializer(many=True)},
    )
    @action(detail=True, methods=["get"])
    def results(self, request: Request, customer_pk: str, pk: str | None = None) -> Response:
        run = self.get_object()
        qs = ReconciliationResult.objects.filter(run=run, customer=run.customer).select_related("reviewed_by")
        p = request.query_params
        kind = p.get("kind", "expected")
        if kind not in ("expected", "unexpected"):
            raise ValidationError({"kind": "expected or unexpected"})
        qs = qs.filter(kind=kind)
        if cls := p.get("classification"):
            classes = [c for c in cls.split(",") if c]
            from django.db.models import Q

            qs = qs.filter(
                Q(reviewed_classification__in=classes) | Q(reviewed_classification="", classification__in=classes)
            )
        if flag := p.get("flag"):
            qs = qs.filter(flags__contains=[flag[:32]])
        if rs := p.get("review_state"):
            qs = qs.filter(review_state=rs[:16])
        page = self.paginate_queryset(qs.order_by("row_number", "id"))
        items = page if page is not None else list(qs)
        context = {"candidates": self._candidates(run, items)}
        data = ReconciliationResultSerializer(items, many=True, context=context).data
        return self.get_paginated_response(data) if page is not None else Response(data)

    def _candidates(self, run: ReconciliationRun, items: list[ReconciliationResult]) -> dict[Any, list[dict[str, Any]]]:
        wanted = {a for r in items for a in r.candidate_asset_ids}
        if not wanted:
            return {}
        devices = {
            d.asset_id: d for d in services.load_devices(run.customer_id, run.generation) if d.asset_id in wanted
        }
        return {
            r.pk: [devices[a].placement() | {"asset_id": a} for a in r.candidate_asset_ids if a in devices]
            for r in items
            if r.candidate_asset_ids
        }

    @extend_schema(request=ReconciliationReviewSerializer, responses={200: ReconciliationResultSerializer})
    @action(detail=True, methods=["post"], url_path=r"results/(?P<result_pk>[0-9a-f-]{36})/review")
    def review(
        self, request: Request, customer_pk: str, pk: str | None = None, result_pk: str | None = None
    ) -> Response:
        run = self.get_object()
        result = ReconciliationResult.objects.filter(run=run, customer=run.customer, pk=_uuid_or_404(result_pk)).first()
        if result is None:
            raise NotFound()
        body = ReconciliationReviewSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        asset = body.validated_data.get("asset")
        try:
            result = services.review(
                result,
                request.user,
                body.validated_data["decision"],
                str(asset) if asset else None,
                body.validated_data["note"],
                request,
            )
        except services.ReviewError as exc:
            raise ValidationError({"detail": exc.message}) from exc
        return Response(
            ReconciliationResultSerializer(result, context={"candidates": self._candidates(run, [result])}).data
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("output", str, enum=["xlsx", "csv"]),
            OpenApiParameter("part", str, enum=["expected", "unexpected"]),
        ],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"])
    def export(self, request: Request, customer_pk: str, pk: str | None = None) -> HttpResponse:
        run = self.get_object()
        if run.state != ReconciliationRun.State.COMPLETED:
            raise NotFound("The comparison has not completed.")
        fmt = request.query_params.get("output", "xlsx")
        part = request.query_params.get("part", "expected")
        if fmt not in ("xlsx", "csv") or part not in ("expected", "unexpected"):
            raise ValidationError({"detail": "output must be xlsx|csv and part expected|unexpected."})
        content, rows = workbook.build_xlsx(run) if fmt == "xlsx" else workbook.build_csv(run, part)
        record_event(
            action="onboarding.exported",
            outcome="success",
            actor=request.user,
            customer=run.customer,
            target_type="reconciliation_run",
            target_id=str(run.id),
            request=request,
            metadata={"format": fmt, "part": part, "rows": rows},
        )
        suffix = "" if fmt == "xlsx" else f"_{part}"
        filename = f"{run.customer.code}_onboarding_{run.created_at:%Y%m%dT%H%M%SZ}{suffix}.{fmt}"
        response = HttpResponse(content, content_type=CONTENT_TYPES[fmt])
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response
