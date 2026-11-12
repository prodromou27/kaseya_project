from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.customers.models import CustomerSourceMapping
from apps.customers.views import CustomerScopedMixin
from apps.integrations.models import SyncRun
from apps.integrations.sync import SyncRefused, request_sync

from .models import Asset, AssetObservation
from .queries import current_generations, current_observations, stale_cutoff

ORDERING = {
    "hostname",
    "-hostname",
    "last_seen_online",
    "-last_seen_online",
    "group_name",
    "-group_name",
    "os_name",
    "-os_name",
}


class AssetRowSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="asset_id")
    external_id = serializers.CharField(source="asset.external_id")
    active = serializers.BooleanField(source="asset.active")
    source = serializers.CharField(source="generation.integration_instance.name")
    data_basis = serializers.CharField(source="generation.data_basis")
    generation_id = serializers.UUIDField(source="generation.id")
    as_of = serializers.DateTimeField(source="generation.published_at")
    last_seen_stale = serializers.SerializerMethodField()

    class Meta:
        model = AssetObservation
        fields = [
            "id",
            "external_id",
            "hostname",
            "description",
            "device_type",
            "group_name",
            "site_external_id",
            "organization_external_id",
            "client_version",
            "last_seen_online",
            "last_seen_stale",
            "os_name",
            "os_version",
            "manufacturer",
            "model",
            "serial_number",
            "domain",
            "tags",
            "software_status",
            "software_count",
            "active",
            "source",
            "data_basis",
            "generation_id",
            "as_of",
        ]

    def get_last_seen_stale(self, obj: AssetObservation) -> bool | None:
        days = self.context.get("offline_days", 7)
        if obj.last_seen_online is None:
            return None
        return obj.last_seen_online < timezone.now() - timedelta(days=days)


class CustomerAssetViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Current published inventory (RPT-01 basis). Server-side search, filters, ordering and pagination."""

    customer_capability = Cap.CUSTOMER_READ
    serializer_class = AssetRowSerializer

    def get_queryset(self) -> QuerySet[AssetObservation]:
        if getattr(self, "swagger_fake_view", False):
            return AssetObservation.objects.none()
        p = self.request.query_params
        qs = current_observations(self.get_customer().id)
        search = p.get("search", "").strip()[:100]
        if search:
            qs = qs.filter(
                Q(hostname__icontains=search) | Q(serial_number__icontains=search) | Q(asset__external_id=search)
            )
        for param, field in (
            ("group", "group_name"),
            ("os", "os_name"),
            ("device_type", "device_type"),
            ("site", "site_external_id"),
            ("software_status", "software_status"),
        ):
            value = p.get(param, "").strip()[:255]
            if value:
                qs = qs.filter(**{field: value})
        offline = p.get("offline")
        if offline in ("true", "false"):
            cutoff = timezone.now() - timedelta(days=self._offline_days())
            cond = Q(last_seen_online__lt=cutoff) | Q(last_seen_online__isnull=True)
            qs = qs.filter(cond) if offline == "true" else qs.exclude(cond)
        ordering = p.get("ordering", "hostname")
        if ordering not in ORDERING:
            raise ValidationError({"ordering": f"Allowed: {', '.join(sorted(ORDERING))}"})
        return qs.order_by(ordering, "asset_id")

    def _offline_days(self) -> int:
        try:
            return max(1, min(int(self.request.query_params.get("offline_days", "7")), 365))
        except ValueError as exc:
            raise ValidationError({"offline_days": "Integer 1-365."}) from exc

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "offline_days": self._offline_days()}

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def facets(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        qs = current_observations(self.get_customer().id)

        def distinct(field: str) -> list[str]:
            return sorted(v for v in qs.order_by().values_list(field, flat=True).distinct() if v)[:500]

        return Response(
            {
                "group": distinct("group_name"),
                "os": distinct("os_name"),
                "device_type": distinct("device_type"),
                "site": distinct("site_external_id"),
            }
        )


class AssetDetailViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """``/assets/{id}/``: customer resolved from the asset row, then authorised."""

    serializer_class = AssetRowSerializer
    queryset = Asset.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        asset = Asset.objects.filter(pk=_uuid(kwargs["pk"])).first()
        scope.get_customer_or_404(request.user, asset.customer_id if asset else None, Cap.CUSTOMER_READ, request)
        assert asset is not None  # noqa: S101 - get_customer_or_404 raised otherwise
        current = current_observations(asset.customer_id).filter(asset=asset).first()
        history = (
            AssetObservation.objects.filter(asset=asset, generation__state__in=["published", "superseded"])
            .select_related("generation")
            .order_by("-generation__published_at")[:20]
        )
        software = []
        if current is not None:
            from apps.software.queries import installation_rows

            software = installation_rows(asset.customer_id, asset_id=asset.id)
        os_updates: dict[str, Any] | None = None
        if current is not None:
            from apps.patching.models import PatchObservation
            from apps.patching.views import DeviceOsUpdateSerializer, DevicePatchStatusSerializer

            po = PatchObservation.objects.filter(observation=current).select_related("observation").first()
            if po is not None:
                updates = po.updates.select_related("os_update", "patch_observation__observation").order_by(
                    "state", "-os_update__kb_article"
                )[:1000]
                os_updates = {
                    "status": DevicePatchStatusSerializer(po).data,
                    "updates": DeviceOsUpdateSerializer(updates, many=True).data,
                }
        return Response(
            {
                "os_updates": os_updates,
                "asset": AssetRowSerializer(current, context={"offline_days": 7}).data if current else None,
                "id": str(asset.id),
                "external_id": asset.external_id,
                "active": asset.active,
                "in_current_dataset": current is not None,
                "software": software,
                "history": [
                    {
                        "generation_id": str(o.generation_id),
                        "published_at": o.generation.published_at,
                        "hostname": o.hostname,
                        "last_seen_online": o.last_seen_online,
                        "os_name": o.os_name,
                        "software_count": o.software_count,
                        "current": o.generation.is_current,
                    }
                    for o in history
                ],
            }
        )


class DatasetStatusViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Freshness per approved source mapping: as-of, last run, staleness (never silently dropped)."""

    customer_capability = Cap.CUSTOMER_READ
    pagination_class = None
    queryset = CustomerSourceMapping.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        cutoff = stale_cutoff()
        out = []
        mappings = CustomerSourceMapping.objects.filter(customer=customer, mapping_status="approved").select_related(
            "integration_instance"
        )
        gens = {g.mapping_id: g for g in current_generations(customer.id)}
        for m in mappings:
            gen = gens.get(m.id)
            last_run = SyncRun.objects.filter(mapping=m).order_by("-created_at").first()
            out.append(
                {
                    "mapping_id": str(m.id),
                    "integration": {
                        "id": str(m.integration_instance_id),
                        "name": m.integration_instance.name,
                        "provider": m.integration_instance.provider,
                        "is_fixture": m.integration_instance.is_fixture,
                        "enabled": m.integration_instance.enabled,
                    },
                    "external_org_id": m.external_org_id,
                    "dataset": "vsa_assets",
                    "status": "never_synced" if gen is None else ("stale" if gen.published_at < cutoff else "fresh"),
                    "as_of": gen.published_at if gen else None,
                    "generation_id": str(gen.id) if gen else None,
                    "row_count": gen.row_count if gen else None,
                    "data_basis": gen.data_basis if gen else None,
                    "last_run": None
                    if last_run is None
                    else {
                        "id": str(last_run.id),
                        "state": last_run.state,
                        "error_code": last_run.error_code,
                        "created_at": last_run.created_at,
                        "ended_at": last_run.ended_at,
                        "fetched": last_run.fetched_count,
                        "quarantined": last_run.quarantined_count,
                    },
                }
            )
        return Response(out)


class SyncRunSerializer(serializers.ModelSerializer):
    integration = serializers.CharField(source="integration_instance.name")
    requested_by = serializers.SlugRelatedField(slug_field="email", read_only=True)

    class Meta:
        model = SyncRun
        fields = [
            "id",
            "integration",
            "dataset",
            "state",
            "trigger",
            "requested_by",
            "pages_fetched",
            "fetched_count",
            "accepted_count",
            "quarantined_count",
            "source_total_count",
            "api_requests",
            "attempts",
            "error_code",
            "created_at",
            "started_at",
            "ended_at",
            "generation",
        ]


class CustomerSyncRunViewSet(CustomerScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = SyncRunSerializer

    def get_customer(self) -> Any:  # POST requires sync capability, GET read
        self.customer_capability = Cap.CUSTOMER_SYNC if self.request.method == "POST" else Cap.CUSTOMER_READ
        return super().get_customer()

    def get_queryset(self) -> QuerySet[SyncRun]:
        if getattr(self, "swagger_fake_view", False):
            return SyncRun.objects.none()
        return SyncRun.objects.filter(customer=self.get_customer()).select_related(
            "integration_instance", "requested_by"
        )

    @extend_schema(request=None, responses={202: SyncRunSerializer(many=True)})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        mappings = CustomerSourceMapping.objects.filter(
            customer=customer, mapping_status="approved", integration_instance__provider="vsa_x"
        ).select_related("integration_instance", "customer")
        if not mappings:
            raise ValidationError({"detail": "No approved VSA X source mapping for this customer."})
        runs, refused = [], []
        for mapping in mappings:
            try:
                run, _ = request_sync(mapping, requested_by=request.user)
                runs.append(run)
            except SyncRefused as exc:
                refused.append({"mapping_id": str(mapping.id), "code": exc.code, "message": str(exc)})
        if not runs:
            raise ValidationError({"detail": refused[0]["message"], "refused": refused})
        data = SyncRunSerializer(SyncRun.objects.filter(pk__in=[r.pk for r in runs]), many=True).data
        return Response({"runs": data, "refused": refused}, status=status.HTTP_202_ACCEPTED)


def _uuid(value: Any) -> Any:
    import uuid

    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise NotFound() from None
