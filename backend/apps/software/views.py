from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin
from apps.inventory.models import Asset

from . import queries
from .catalog import approve_import, build_preview, check_reviewer, schedule_reevaluation
from .models import (
    CatalogImport,
    CatalogRevision,
    ComplianceResult,
    ReviewStatus,
    SoftwareAlias,
    SoftwareException,
    SoftwareProduct,
)

# ---------------------------------------------------------------------------------------------- customer side


class ResultRowSerializer(serializers.Serializer):
    """Read-only row; see ``queries.result_row``."""

    def to_representation(self, instance: ComplianceResult) -> dict[str, Any]:
        row = queries.result_row(instance)
        row["hostname"] = self.context.get("hostnames", {}).get(instance.asset_id)
        return row


class CustomerSoftwareViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """``/customers/{id}/software/`` — installations with classification and catalog evidence (RPT-02/03)."""

    customer_capability = Cap.CUSTOMER_READ
    serializer_class = ResultRowSerializer

    def get_queryset(self) -> QuerySet[ComplianceResult]:
        if getattr(self, "swagger_fake_view", False):
            return ComplianceResult.objects.none()
        return queries.filtered_results(self.get_customer().id, self.request.query_params).order_by(
            "installation__raw_name", "installation__raw_version", "id"
        )

    def get_serializer_context(self) -> dict[str, Any]:
        ctx = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False) and "customer_pk" in self.kwargs:
            from apps.inventory.queries import current_observations

            ctx["hostnames"] = dict(current_observations(self.get_customer().id).values_list("asset_id", "hostname"))
        return ctx

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(queries.summary(self.get_customer().id))


class ExceptionSerializer(serializers.ModelSerializer):
    approved_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    product_label = serializers.CharField(source="product.__str__", read_only=True)
    asset = serializers.UUIDField(source="asset_id", required=False, allow_null=True)

    class Meta:
        model = SoftwareException
        fields = [
            "id",
            "product",
            "product_label",
            "asset",
            "reason",
            "approved_by",
            "approved_at",
            "expires_at",
            "status",
            "revoked_at",
        ]
        read_only_fields = ["id", "approved_by", "approved_at", "status", "revoked_at"]

    def validate_expires_at(self, value: Any) -> Any:
        now = timezone.now()
        if value <= now or value > now + timedelta(days=366):
            raise serializers.ValidationError("Expiry must be in the future and within 12 months.")
        return value

    def validate_reason(self, value: str) -> str:
        if len(value.strip()) < 10:
            raise serializers.ValidationError("Give a meaningful justification (min 10 characters).")
        return value.strip()


class CustomerExceptionViewSet(
    CustomerScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ExceptionSerializer

    def get_customer(self) -> Any:
        self.customer_capability = Cap.CUSTOMER_READ if self.request.method == "GET" else Cap.CUSTOMER_MANAGE_EXCEPTIONS
        return super().get_customer()

    def get_queryset(self) -> QuerySet[SoftwareException]:
        if getattr(self, "swagger_fake_view", False):
            return SoftwareException.objects.none()
        return SoftwareException.objects.filter(customer=self.get_customer()).select_related("product", "approved_by")

    def perform_create(self, serializer: ExceptionSerializer) -> None:
        customer = self.get_customer()
        asset_id = serializer.validated_data.pop("asset_id", None)
        if asset_id is not None and not Asset.objects.filter(pk=asset_id, customer=customer).exists():
            raise ValidationError({"asset": "Asset not found for this customer."})  # no cross-customer reference
        with transaction.atomic():
            exc = serializer.save(customer=customer, approved_by=self.request.user, asset_id=asset_id)
            schedule_reevaluation(customer.id)
        record_event(
            action="software_exception.created",
            outcome="success",
            actor=self.request.user,
            customer=customer,
            target_type="software_exception",
            target_id=str(exc.id),
            request=self.request,
            metadata={
                "product": str(exc.product_id),
                "asset": str(asset_id) if asset_id else None,
                "expires_at": exc.expires_at.isoformat(),
            },
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        exc = self.get_object()
        with transaction.atomic():
            exc.status, exc.revoked_by, exc.revoked_at = SoftwareException.Status.REVOKED, request.user, timezone.now()
            exc.save(update_fields=["status", "revoked_by", "revoked_at"])
            schedule_reevaluation(exc.customer_id)
        record_event(
            action="software_exception.revoked",
            outcome="success",
            actor=request.user,
            customer=exc.customer,
            target_type="software_exception",
            target_id=str(exc.id),
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------------------------- catalog (admin)


class ProductSerializer(serializers.ModelSerializer):
    current_reference = serializers.SerializerMethodField()

    class Meta:
        model = SoftwareProduct
        fields = [
            "id",
            "vendor",
            "product",
            "edition",
            "platform",
            "channel",
            "architecture",
            "notes",
            "active",
            "created_at",
            "current_reference",
        ]
        read_only_fields = ["id", "created_at", "current_reference"]

    def get_current_reference(self, obj: SoftwareProduct) -> dict[str, Any] | None:
        rev = (
            obj.revisions.filter(state="published", effective_at__lte=timezone.now()).order_by("-effective_at").first()
        )
        return (
            None
            if rev is None
            else {
                "id": str(rev.id),
                "reference_version": rev.reference_version,
                "effective_at": rev.effective_at,
                "vendor_url": rev.vendor_url,
            }
        )


class ProductViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsSystemAdmin]
    serializer_class = ProductSerializer
    queryset = SoftwareProduct.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]

    def perform_create(self, serializer: ProductSerializer) -> None:
        product = serializer.save()
        record_event(
            action="catalog.product_created",
            outcome="success",
            actor=self.request.user,
            target_type="software_product",
            target_id=str(product.id),
            request=self.request,
        )

    def perform_update(self, serializer: ProductSerializer) -> None:
        with transaction.atomic():
            product = serializer.save()
            schedule_reevaluation()
        record_event(
            action="catalog.product_updated",
            outcome="success",
            actor=self.request.user,
            target_type="software_product",
            target_id=str(product.id),
            request=self.request,
            metadata={"changed": sorted(serializer.validated_data)},
        )


class AliasSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = SoftwareAlias
        fields = [
            "id",
            "product",
            "name_pattern",
            "publisher_pattern",
            "match_type",
            "review_status",
            "created_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = ["id", "review_status", "created_by", "reviewed_by", "reviewed_at", "created_at"]

    def validate_name_pattern(self, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Pattern too short (min 3 characters).")
        return value


class AliasViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Aliases are proposed, then approved by a (separate) reviewer before they influence classification."""

    permission_classes = [IsSystemAdmin]
    serializer_class = AliasSerializer
    queryset = SoftwareAlias.objects.select_related("created_by", "reviewed_by").all()

    def get_queryset(self) -> QuerySet[SoftwareAlias]:
        qs = super().get_queryset()
        st = self.request.query_params.get("review_status")
        return qs.filter(review_status=st) if st in ReviewStatus.values else qs

    def perform_create(self, serializer: AliasSerializer) -> None:
        alias = serializer.save(created_by=self.request.user, review_status=ReviewStatus.PROPOSED)
        record_event(
            action="catalog.alias_proposed",
            outcome="success",
            actor=self.request.user,
            target_type="software_alias",
            target_id=str(alias.id),
            request=self.request,
            metadata={"pattern": alias.name_pattern, "product": str(alias.product_id)},
        )

    def _review(self, request: Request, new_status: str) -> Response:
        alias = self.get_object()
        if alias.review_status != ReviewStatus.PROPOSED:
            raise ValidationError({"review_status": f"Alias is already {alias.review_status}."})
        check_reviewer(alias.created_by_id, request.user)
        with transaction.atomic():
            alias.review_status, alias.reviewed_by, alias.reviewed_at = new_status, request.user, timezone.now()
            alias.save(update_fields=["review_status", "reviewed_by", "reviewed_at"])
            if new_status == ReviewStatus.APPROVED:
                schedule_reevaluation()
        record_event(
            action=f"catalog.alias_{new_status}",
            outcome="success",
            actor=request.user,
            target_type="software_alias",
            target_id=str(alias.id),
            request=request,
        )
        return Response(AliasSerializer(alias).data)

    @extend_schema(request=None, responses={200: AliasSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        return self._review(request, ReviewStatus.APPROVED)

    @extend_schema(request=None, responses={200: AliasSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        return self._review(request, ReviewStatus.REJECTED)


class RevisionSerializer(serializers.ModelSerializer):
    product_label = serializers.CharField(source="product.__str__", read_only=True)
    created_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = CatalogRevision
        fields = [
            "id",
            "product",
            "product_label",
            "reference_version",
            "version_scheme",
            "vendor_url",
            "source_type",
            "source_checked_at",
            "effective_at",
            "state",
            "catalog_import",
            "created_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = fields


class RevisionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsSystemAdmin]
    serializer_class = RevisionSerializer
    queryset = CatalogRevision.objects.select_related("product", "created_by", "reviewed_by").all()

    @extend_schema(request=None, responses={200: RevisionSerializer})
    @action(detail=True, methods=["post"])
    def retire(self, request: Request, pk: str | None = None) -> Response:
        rev = self.get_object()
        if rev.state != CatalogRevision.State.PUBLISHED:
            raise ValidationError({"state": "Only published revisions can be retired."})
        with transaction.atomic():
            rev.state = CatalogRevision.State.RETIRED
            rev.save(update_fields=["state"])
            schedule_reevaluation()
        record_event(
            action="catalog.revision_retired",
            outcome="success",
            actor=request.user,
            target_type="catalog_revision",
            target_id=str(rev.id),
            request=request,
        )
        return Response(RevisionSerializer(rev).data)


class ImportSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = CatalogImport
        fields = [
            "id",
            "state",
            "rows",
            "preview",
            "created_by",
            "created_at",
            "reviewed_by",
            "reviewed_at",
            "review_note",
        ]
        read_only_fields = [
            "id",
            "state",
            "preview",
            "created_by",
            "created_at",
            "reviewed_by",
            "reviewed_at",
            "review_note",
        ]


class ImportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsSystemAdmin]
    serializer_class = ImportSerializer
    queryset = CatalogImport.objects.select_related("created_by", "reviewed_by").all()

    @extend_schema(request=ImportSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def preview(self, request: Request) -> Response:
        """Dry run: validates rows and shows the effect, saves nothing."""
        preview, valid = build_preview(request.data.get("rows"))
        return Response({"valid": valid, "rows": preview})

    def perform_create(self, serializer: ImportSerializer) -> None:
        preview, valid = build_preview(serializer.validated_data.get("rows"))
        if not valid:
            raise ValidationError({"rows": "Fix the invalid rows first.", "preview": preview})
        imp = serializer.save(created_by=self.request.user, preview=preview)
        record_event(
            action="catalog.import_submitted",
            outcome="success",
            actor=self.request.user,
            target_type="catalog_import",
            target_id=str(imp.id),
            request=self.request,
            metadata={"rows": len(imp.rows)},
        )

    @extend_schema(request=None, responses={200: ImportSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        imp = self.get_object()
        revisions = approve_import(imp, request.user)
        imp.refresh_from_db()
        record_event(
            action="catalog.import_approved",
            outcome="success",
            actor=request.user,
            target_type="catalog_import",
            target_id=str(imp.id),
            request=request,
            metadata={"revisions": [str(r.id) for r in revisions]},
        )
        return Response(ImportSerializer(imp).data)

    @extend_schema(request=None, responses={200: ImportSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        imp = self.get_object()
        if imp.state != CatalogImport.State.PENDING:
            raise ValidationError({"state": f"Import is {imp.state}."})
        imp.state, imp.reviewed_by, imp.reviewed_at = CatalogImport.State.REJECTED, request.user, timezone.now()
        imp.review_note = str(request.data.get("note", ""))[:2000]
        imp.save(update_fields=["state", "reviewed_by", "reviewed_at", "review_note"])
        record_event(
            action="catalog.import_rejected",
            outcome="success",
            actor=request.user,
            target_type="catalog_import",
            target_id=str(imp.id),
            request=request,
        )
        return Response(ImportSerializer(imp).data)
