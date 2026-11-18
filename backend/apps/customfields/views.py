"""CFA API. Customer-scoped (``/customers/{id}/custom-field…``) plus system field settings.

The customer always comes from the URL and the access policy; field, device and item IDs from a request body are only
ever looked up *within* that customer / its mapped integrations, so they cannot reach anything else.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from . import definitions, jobs, matching, report
from .models import AssignmentItem, AssignmentJob, CustomFieldDefinition

READ_ACTIONS = {"list", "retrieve", "items", "device_values", "report"}


class DefinitionSerializer(serializers.ModelSerializer):
    integration = serializers.CharField(source="integration_instance.name", read_only=True)
    editable = serializers.SerializerMethodField()
    reason = serializers.SerializerMethodField()
    device_capable = serializers.SerializerMethodField()

    class Meta:
        model = CustomFieldDefinition
        fields = (
            "id",
            "external_id",
            "name",
            "description",
            "type",
            "default_value",
            "is_read_only",
            "contexts",
            "expiration_date",
            "present",
            "fetched_at",
            "portal_writable",
            "requires_approval",
            "integration",
            "editable",
            "device_capable",
            "reason",
        )
        read_only_fields = tuple(f for f in fields if f not in ("portal_writable", "requires_approval"))

    def get_editable(self, obj: CustomFieldDefinition) -> bool:
        return definitions.eligibility(obj)[0]

    def get_device_capable(self, obj: CustomFieldDefinition) -> bool:
        return definitions.device_capable(obj)[0]

    def get_reason(self, obj: CustomFieldDefinition) -> str:
        return definitions.eligibility(obj)[1]

    def validate_portal_writable(self, value: bool) -> bool:
        if value and self.instance is not None:
            ok, reason = definitions.device_capable(self.instance)
            if not ok:
                raise serializers.ValidationError(f"Cannot be edited: {reason}.")
        return value


class ItemSerializer(serializers.ModelSerializer):
    match_label = serializers.CharField(source="get_match_status_display", read_only=True)
    action_label = serializers.CharField(source="get_action_display", read_only=True)
    result_label = serializers.CharField(source="get_result_display", read_only=True)

    class Meta:
        model = AssignmentItem
        fields = (
            "id",
            "position",
            "input_identifier",
            "input_kind",
            "input_row",
            "match_status",
            "match_label",
            "match_note",
            "candidates",
            "asset",
            "device_external_id",
            "hostname",
            "site",
            "group",
            "requested_value",
            "included",
            "current_value",
            "current_source",
            "device_assigned",
            "action",
            "action_label",
            "action_note",
            "result",
            "result_label",
            "final_value",
            "http_status",
            "error_code",
            "finished_at",
        )


class JobSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField(source="field.name", read_only=True)
    field_type = serializers.CharField(source="field.type", read_only=True)
    field_external_id = serializers.CharField(source="field.external_id", read_only=True)
    integration = serializers.CharField(source="integration_instance.name", read_only=True)
    created_by = serializers.EmailField(source="created_by.email", read_only=True)
    confirmed_by = serializers.SerializerMethodField()
    approved_by = serializers.SerializerMethodField()
    state_label = serializers.CharField(source="get_state_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    writes = serializers.SerializerMethodField()

    class Meta:
        model = AssignmentJob
        fields = (
            "id",
            "field",
            "field_name",
            "field_type",
            "field_external_id",
            "integration",
            "value",
            "per_device_values",
            "source",
            "source_label",
            "source_filename",
            "retry_of",
            "state",
            "state_label",
            "created_by",
            "created_at",
            "previewed_at",
            "confirmed_by",
            "confirmed_at",
            "approval_required",
            "approved_by",
            "approved_at",
            "cancel_requested",
            "started_at",
            "finished_at",
            "error_code",
            "counts",
            "writes",
        )

    def get_confirmed_by(self, obj: AssignmentJob) -> str | None:
        return obj.confirmed_by.email if obj.confirmed_by else None

    def get_approved_by(self, obj: AssignmentJob) -> str | None:
        return obj.approved_by.email if obj.approved_by else None

    def get_writes(self, obj: AssignmentJob) -> dict[str, Any]:
        from apps.integrations.vsa.cf_writer import availability

        ok, reason = availability(obj.integration_instance)
        return {"available": ok, "reason": reason}


class ItemPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500


class CustomFieldViewSet(CustomerScopedMixin, viewsets.ViewSet):
    """``/customers/{id}/custom-fields/`` - definitions of the customer's VSA X integrations; refresh; device values."""

    def get_customer(self) -> Any:
        self.customer_capability = Cap.CUSTOMER_READ if self.action in READ_ACTIONS else Cap.CUSTOMER_CF_ASSIGN
        return super().get_customer()

    @extend_schema(responses={200: DefinitionSerializer(many=True)})
    def list(self, request: Request, customer_pk: str | None = None) -> Response:
        qs = definitions.for_customer(self.get_customer()).filter(present=True)
        if request.query_params.get("editable") == "true":
            qs = qs.filter(portal_writable=True)
        return Response(DefinitionSerializer(qs, many=True).data)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def refresh(self, request: Request, customer_pk: str | None = None) -> Response:
        """Re-read the field list from VSA X (read-only)."""
        from apps.customers.models import CustomerSourceMapping
        from apps.integrations.models import IntegrationInstance

        customer = self.get_customer()
        ids = CustomerSourceMapping.objects.filter(customer=customer, mapping_status="approved").values(
            "integration_instance_id"
        )
        out = {}
        for instance in IntegrationInstance.objects.filter(id__in=ids, provider="vsa_x", enabled=True):
            try:
                out[instance.name] = definitions.refresh(instance)
            except Exception as exc:
                out[instance.name] = {"error": type(exc).__name__}
        record_event(
            action="custom_field.definitions_refreshed",
            outcome="success",
            actor=request.user,
            customer=customer,
            target_type="customer",
            target_id=str(customer.id),
            request=request,
            metadata={"result": out},
        )
        return Response({"result": out})

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path=r"device/(?P<asset_id>[0-9a-f-]{36})")
    def device_values(self, request: Request, customer_pk: str | None = None, asset_id: str = "") -> Response:
        """Editable fields with the value VSA X reports now for one device (device page)."""
        from apps.integrations.vsa.adapter import VsaXAdapter
        from apps.inventory.queries import current_observations

        customer = self.get_customer()
        obs = current_observations(customer.id).filter(asset_id=asset_id).select_related("asset").first()
        if obs is None:
            raise NotFound()
        instance = obs.asset.integration_instance
        fields = [
            f
            for f in definitions.for_customer(customer).filter(integration_instance=instance, portal_writable=True)
            if definitions.eligibility(f)[0]
        ]
        rows, error = {}, ""
        if fields:
            try:
                rows = {str(r.get("Id")): r for r in VsaXAdapter(instance).get_custom_fields(obs.asset.external_id)}
            except Exception:
                error = "Current values could not be read from VSA X."
        workstation = next(iter(matching.match_selected(customer, instance, [str(asset_id)])))
        return Response(
            {
                "workstation": workstation["match_status"] == AssignmentItem.Match.MATCHED,
                "note": workstation.get("match_note", ""),
                "error": error,
                "fields": [
                    {
                        **DefinitionSerializer(f).data,
                        "value": None if error else (rows.get(f.external_id) or {}).get("Value"),
                    }
                    for f in fields
                ],
            }
        )


class JobViewSet(CustomerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """``/customers/{id}/custom-field-jobs/`` - create, review, preview, confirm, approve, cancel, report."""

    serializer_class = JobSerializer
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_customer(self) -> Any:
        caps = {
            "approve": Cap.CUSTOMER_CF_APPROVE,
            "reject": Cap.CUSTOMER_CF_APPROVE,
            "report": Cap.CUSTOMER_EXPORT,
        }
        self.customer_capability = caps.get(
            self.action, Cap.CUSTOMER_READ if self.action in READ_ACTIONS else Cap.CUSTOMER_CF_ASSIGN
        )
        return super().get_customer()

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return AssignmentJob.objects.none()
        qs = AssignmentJob.objects.filter(customer=self.get_customer()).select_related(
            "field", "integration_instance", "created_by", "confirmed_by", "approved_by"
        )
        if state := self.request.query_params.get("state"):
            qs = qs.filter(state=state)
        return qs

    def _job(self) -> AssignmentJob:
        try:
            return self.get_queryset().get(pk=uuid.UUID(str(self.kwargs["pk"])))
        except (ValueError, AssignmentJob.DoesNotExist) as exc:
            raise NotFound() from exc

    def _field(self, field_id: Any) -> CustomFieldDefinition:
        try:
            return definitions.for_customer(self.get_customer()).get(pk=uuid.UUID(str(field_id)))
        except (ValueError, CustomFieldDefinition.DoesNotExist) as exc:
            raise ValidationError({"field": "Choose a custom field of this customer's VSA X integration."}) from exc

    @extend_schema(request=OpenApiTypes.OBJECT, responses={201: JobSerializer})
    def create(self, request: Request, customer_pk: str | None = None) -> Response:
        """JSON ``{field, value, source, assets?, text?}`` or multipart ``file`` + ``mapping``."""
        customer = self.get_customer()
        data = request.data
        field = self._field(data.get("field"))
        instance = field.integration_instance
        upload = request.FILES.get("file")
        if upload is not None:
            mapping = _mapping(data.get("mapping"))
            _header, rows = matching.read_file(upload.name, upload.read())
            items = matching.match(customer, request.user, instance, matching.from_rows(rows, mapping))
            source, filename = AssignmentJob.Source.IMPORT, upload.name
        elif data.get("source") == "list":
            items = matching.match(customer, request.user, instance, matching.from_text(data.get("text", "")))
            source, filename = AssignmentJob.Source.LIST, ""
        else:
            assets = data.get("assets")
            if isinstance(data.get("filters"), dict):
                assets = _filtered_assets(customer, instance, data["filters"])  # resolved once: an immutable list
            items = matching.match_selected(customer, instance, assets if isinstance(assets, list) else [])
            source = AssignmentJob.Source.DEVICE if data.get("source") == "device" else AssignmentJob.Source.SELECTION
            filename = ""
        job = jobs.create(
            customer,
            request.user,
            field,
            value=str(data.get("value") or ""),
            source=source,
            items=items,
            filename=filename,
            request=request,
        )
        return Response(JobSerializer(job).data, status=201)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"], url_path="inspect-file")
    def inspect_file(self, request: Request, customer_pk: str | None = None) -> Response:
        """Columns and the first rows of an uploaded TXT/CSV/XLSX, with a suggested column mapping. Saves nothing."""
        self.get_customer()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Choose a file."})
        header, rows = matching.read_file(upload.name, upload.read())
        return Response(
            {
                "columns": header,
                "rows": len(rows),
                "sample": [cells for _, cells in rows[:5]],
                "mapping": matching.guess_mapping(header),
                "roles": matching.ROLES,
            }
        )

    @extend_schema(responses={200: ItemSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def items(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        qs = self._job().items.all().select_related(None)
        params = request.query_params
        for key, fieldname in (("match", "match_status"), ("action", "action"), ("result", "result")):
            if value := params.get(key):
                qs = qs.filter(**{f"{fieldname}__in": value.split(",")})
        if search := (params.get("search") or "").strip()[:100]:
            qs = qs.filter(Q(input_identifier__icontains=search) | Q(hostname__icontains=search))
        paginator = ItemPagination()
        page = paginator.paginate_queryset(qs.order_by("position"), request, view=self)
        return paginator.get_paginated_response(ItemSerializer(page, many=True).data)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: ItemSerializer})
    @action(detail=True, methods=["post"])
    def resolve(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        job = self._job()
        asset = request.data.get("asset")
        item = jobs.resolve(
            job, _uuid(request.data.get("item"), "item"), None if asset is None else str(asset), request.user
        )
        return Response(ItemSerializer(item).data)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: JobSerializer})
    @action(detail=True, methods=["post"])
    def include(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        ids = request.data.get("items")
        if not isinstance(ids, list) or len(ids) > 5000:
            raise ValidationError({"items": "Provide a list of item IDs."})
        job = self._job()
        jobs.set_included(job, [_uuid(i, "items") for i in ids], bool(request.data.get("included")))
        job.refresh_from_db()
        return Response(JobSerializer(job).data)

    @extend_schema(request=None, responses={200: JobSerializer})
    @action(detail=True, methods=["post"])
    def preview(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        job = jobs.request_preview(self._job(), request.user, request)
        return Response(JobSerializer(job).data)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: JobSerializer})
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        if request.data.get("confirm") is not True:
            raise ValidationError({"confirm": "Confirm the change explicitly."})
        job = jobs.confirm(
            self._job(),
            request.user,
            acknowledge_overwrite=request.data.get("acknowledge_overwrite") is True,
            request=request,
        )
        job.refresh_from_db()
        return Response(JobSerializer(job).data)

    @extend_schema(request=None, responses={200: JobSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        job = jobs.decide(self._job(), request.user, approve=True, request=request)
        job.refresh_from_db()
        return Response(JobSerializer(job).data)

    @extend_schema(request=None, responses={200: JobSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        job = jobs.decide(self._job(), request.user, approve=False, request=request)
        return Response(JobSerializer(job).data)

    @extend_schema(request=None, responses={200: JobSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        job = jobs.cancel(self._job(), request.user, request)
        job.refresh_from_db()
        return Response(JobSerializer(job).data)

    @extend_schema(request=None, responses={201: JobSerializer})
    @action(detail=True, methods=["post"])
    def retry(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> Response:
        """New draft job for the devices that did not end verified (preview and confirm again)."""
        job = jobs.retry_failed(self._job(), request.user, request)
        return Response(JobSerializer(job).data, status=201)

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def report(self, request: Request, customer_pk: str | None = None, pk: str | None = None) -> HttpResponse:
        job = self._job()
        fmt = request.query_params.get("type", "xlsx")  # not "format": DRF reserves it for content negotiation
        if fmt not in ("csv", "xlsx"):
            raise ValidationError({"type": "csv or xlsx"})
        body = report.render_csv(job) if fmt == "csv" else report.render_xlsx(job)
        record_event(
            action="custom_field.report_exported",
            outcome="success",
            actor=request.user,
            customer=job.customer,
            target_type="custom_field_job",
            target_id=str(job.id),
            request=request,
            metadata={"format": fmt},
        )
        stamp = timezone.now().strftime("%Y%m%d-%H%M")
        resp = HttpResponse(
            body,
            content_type="text/csv; charset=utf-8"
            if fmt == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="custom-field-job-{stamp}.{fmt}"'
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class DefinitionSettingsViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """``/custom-field-definitions/`` - system administrators choose which fields the portal may edit."""

    permission_classes = [IsSystemAdmin]
    serializer_class = DefinitionSerializer
    http_method_names = ["get", "patch", "head", "options"]
    queryset = CustomFieldDefinition.objects.select_related("integration_instance").filter(present=True)
    pagination_class = None

    def perform_update(self, serializer: DefinitionSerializer) -> None:
        before = {k: getattr(serializer.instance, k) for k in ("portal_writable", "requires_approval")}
        d = serializer.save(settings_changed_by=self.request.user, settings_changed_at=timezone.now())
        record_event(
            action="custom_field.settings_changed",
            outcome="success",
            actor=self.request.user,
            target_type="custom_field_definition",
            target_id=str(d.id),
            request=self.request,
            metadata={
                "field_id": d.external_id,
                "field": d.name,
                "before": before,
                "after": {"portal_writable": d.portal_writable, "requires_approval": d.requires_approval},
            },
        )


def _filtered_assets(customer: Any, instance: Any, raw: dict[str, Any]) -> list[str]:
    """'Select all matching': the inventory filters are resolved to a fixed device list when the job is created."""
    from django.conf import settings

    from apps.inventory.filters import AssetFilters, filter_inventory
    from apps.inventory.queries import current_observations

    filters = AssetFilters(data={k: v for k, v in raw.items() if v not in ("", None)})
    filters.is_valid(raise_exception=True)
    qs = filter_inventory(current_observations(customer.id), filters.validated_data).filter(
        asset__integration_instance=instance
    )
    ids = [str(a) for a in qs.values_list("asset_id", flat=True)[: settings.CUSTOM_FIELD_MAX_JOB_ITEMS + 1]]
    if len(ids) > settings.CUSTOM_FIELD_MAX_JOB_ITEMS:
        raise ValidationError({"filters": f"More than {settings.CUSTOM_FIELD_MAX_JOB_ITEMS} devices match. Narrow it."})
    return ids


def _uuid(value: Any, name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ValidationError({name: "Invalid identifier."}) from exc


def _mapping(raw: Any) -> dict[str, int]:
    try:
        mapping = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise ValidationError({"mapping": "Invalid column mapping."}) from exc
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and 0 <= v < 64 for k, v in mapping.items()
    ):
        raise ValidationError({"mapping": "Invalid column mapping."})
    return mapping
