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
from apps.software.capability import THIRD_PARTY_PATCH_STATUS

from .filters import AssetFilters, filter_inventory
from .hierarchy import group_network, hierarchy
from .models import Asset, AssetObservation
from .queries import current_generations, current_observations, stale_cutoff


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
            "site_name",
            "group_external_id",
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
        customer = self.get_customer()
        filters = AssetFilters(data={k: v for k, v in self.request.query_params.items() if v != ""})
        filters.is_valid(raise_exception=True)
        return filter_inventory(current_observations(customer.id), filters.validated_data)

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
        asset = Asset.objects.select_related("customer").filter(pk=_uuid(kwargs["pk"])).first()
        scope.get_customer_or_404(request.user, asset.customer_id if asset else None, Cap.CUSTOMER_READ, request)
        if asset is None:  # unreachable: get_customer_or_404 already raised; explicit for python -O
            raise NotFound()
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
        details: dict[str, Any] | None = None
        if current is not None:
            from .hierarchy import adapter_payload

            details = {
                "network_status": current.network_status,
                "public_ip": current.public_ip,
                "adapters": [adapter_payload(a) for a in current.adapters.prefetch_related("ips").order_by("name")],
                "disks_status": current.disks_status,
                "disks": [
                    {
                        "name": d.name,
                        "is_system": d.is_system,
                        "free_percentage": d.free_percentage,
                        "total_value_raw": d.total_value_raw,
                    }
                    for d in current.disks.order_by("name")
                ],
                "security_status": current.security_status,
                "security": [
                    {"type": s.type, "name": s.name, "enabled": s.enabled, "up_to_date": s.up_to_date}
                    for s in current.security_items.order_by("type", "name")
                ],
                "group_external_id": current.group_external_id,
                "site_name": current.site_name,
                "is_agent_installed": current.is_agent_installed,
                "is_mdm_enrolled": current.is_mdm_enrolled,
                "units_note": "Disk TotalValue units are not documented by VSA X and are shown as reported.",
            }
        policies: dict[str, Any] | None = None
        if current is not None:
            from apps.patching.models import AppliedPolicyObservation, PatchPolicyDefinition
            from apps.patching.policy_queries import NOTE as POLICY_NOTE

            pol = AppliedPolicyObservation.objects.filter(observation=current).first()
            definition = None
            if pol is not None and pol.patch_policy_id:
                d = PatchPolicyDefinition.objects.filter(
                    customer_id=asset.customer_id, generation_id=current.generation_id, policy_id=pol.patch_policy_id
                ).first()
                if d is not None:
                    definition = {
                        "status": d.status,
                        "name": d.name,
                        "description": d.description,
                        "general_settings": d.general_settings,
                        "os_rules": d.os_rules,
                        "software_rules": d.software_rules,
                    }
            policies = {
                "collection_status": pol.status if pol else "not_collected",
                "collected_at": pol.collected_at.isoformat() if pol and pol.collected_at else None,
                "patch_state": pol.patch_state if pol else "unknown",
                "patch_policy_id": pol.patch_policy_id if pol else "",
                "patch_policy_name": pol.patch_policy_name if pol else "",
                "applied": [
                    {"type": p.policy_type, "id": p.policy_id, "name": p.policy_name, "profiles": p.profiles}
                    for p in (pol.policies.order_by("policy_type") if pol else [])
                ],
                "definition": definition,
                "note": POLICY_NOTE,
            }
        # VSA1-05 reconciliation tab: this device's onboarding results (matched, candidate or unexpected), newest first.
        from apps.onboarding.models import ReconciliationResult

        recon = [
            {
                "run_id": str(r.run_id),
                "run_created_at": r.run.created_at,
                "upload_name": r.run.upload_name,
                "kind": r.kind,
                "row_number": r.row_number,
                "classification": r.classification,
                "reviewed_classification": r.reviewed_classification,
                "flags": r.flags,
                "role": "matched"
                if r.asset_id == asset.id
                else ("candidate" if str(asset.id) in r.candidate_asset_ids else "reviewed_match"),
            }
            for r in ReconciliationResult.objects.filter(customer_id=asset.customer_id, run__state="completed")
            .filter(Q(asset=asset) | Q(reviewed_asset=asset) | Q(candidate_asset_ids__contains=[str(asset.id)]))
            .select_related("run")
            .order_by("-run__created_at")[:20]
        ]
        device_health = None
        if current is not None:
            from .health import device_for

            device_health = device_for(current)
        device_notifications = None
        custom_fields = None
        if current is not None:
            from django.conf import settings as dj_settings

            from .models import DeviceDetailFetch

            fetches = {f.kind: f for f in DeviceDetailFetch.objects.filter(observation=current)}

            def fetch_meta(kind: str) -> dict[str, Any]:
                f = fetches.get(kind)
                return {
                    "status": f.status if f else "not_collected",
                    "collected_at": f.collected_at.isoformat() if f and f.collected_at else None,
                    "reported": f.reported if f else None,
                    "stored": f.stored if f else None,
                    "dropped": f.dropped if f else None,
                }

            nf = fetches.get("notifications")
            device_notifications = {
                **fetch_meta("notifications"),
                "window_days": dj_settings.NOTIFICATION_WINDOW_DAYS,
                "items": [
                    {
                        "priority": n.priority,
                        "occurred_at": n.occurred_at.isoformat() if n.occurred_at else None,
                        "occurred_raw": n.occurred_raw,
                        "message": n.message,
                        "redactions": n.redactions,
                    }
                    for n in (nf.notifications.order_by("-occurred_at")[:100] if nf else [])
                ],
            }
            cf = fetches.get("custom_fields")
            custom_fields = {
                **fetch_meta("custom_fields"),
                "items": [
                    {"name": c.name, "value": c.value, "type": c.type}
                    for c in (cf.custom_fields.order_by("name") if cf else [])
                ],
            }
        return Response(
            {
                "details": details,
                "health": device_health,
                "notifications": device_notifications,
                "custom_fields": custom_fields,
                "reconciliation": recon,
                "policies": policies,
                "third_party_patch_status": THIRD_PARTY_PATCH_STATUS,
                "os_updates": os_updates,
                "asset": AssetRowSerializer(current, context={"offline_days": 7}).data if current else None,
                "id": str(asset.id),
                "customer": {"id": str(asset.customer_id), "code": asset.customer.code, "name": asset.customer.name},
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


class CustomerHierarchyViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    """``/customers/{id}/hierarchy/`` — organisation > site > group tree with device counts (VSA1-06)."""

    customer_capability = Cap.CUSTOMER_READ
    queryset = AssetObservation.objects.none()

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            days = max(1, min(int(request.query_params.get("stale_days", "7")), 365))
        except ValueError as exc:
            raise ValidationError({"stale_days": "Integer 1-365."}) from exc
        return Response(hierarchy(self.get_customer().id, days))


class CustomerGroupViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    """``/customers/{id}/groups/{group_id}/network/`` — reported network facts for one VSA group (VSA2-05)."""

    customer_capability = Cap.CUSTOMER_READ
    queryset = AssetObservation.objects.none()
    lookup_value_regex = "[0-9]{1,18}"

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get"])
    def network(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        customer = self.get_customer()
        instance = request.query_params.get("instance")
        if instance:
            instance = str(_uuid(instance))
        data = group_network(customer.id, str(pk), instance)
        if data is None:
            raise NotFound()
        return Response(data)
