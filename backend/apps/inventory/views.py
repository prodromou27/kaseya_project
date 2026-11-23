from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
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
from .queries import DATASET, current_generations, current_observations, stale_cutoff


class AssetRowSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="asset_id")
    instance_id = serializers.UUIDField(source="generation.integration_instance_id")
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
            "instance_id",
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
                "sites": list(
                    qs.order_by("site_name", "site_external_id")
                    .values(
                        "site_external_id",
                        "site_name",
                        "generation__integration_instance_id",
                        "generation__integration_instance__name",
                    )
                    .distinct()[:500]
                ),
                "groups": list(
                    qs.order_by("group_name", "group_external_id")
                    .values(
                        "group_external_id",
                        "group_name",
                        "site_name",
                        "generation__integration_instance_id",
                        "generation__integration_instance__name",
                    )
                    .distinct()[:500]
                ),
            }
        )


class AssetDetailViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """``/assets/{id}/``: customer resolved from the asset row, then authorised."""

    serializer_class = AssetRowSerializer
    queryset = Asset.objects.none()

    @extend_schema(
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, description="Hostname, serial or device ID.")],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def lookup(self, request: Request) -> Response:
        """Find a device across every customer the user may read (current inventory only), at most 10 matches."""
        q = serializers.CharField(min_length=2, max_length=100, trim_whitespace=True).run_validation(
            request.query_params.get("q", "")
        )
        rows = scope.scope_queryset(
            AssetObservation.objects.filter(
                generation__is_current=True,
                generation__dataset=DATASET,
                generation__mapping__mapping_status="approved",
            ),
            request.user,
            Cap.CUSTOMER_READ,
        )
        rows = (
            rows.filter(Q(hostname__icontains=q) | Q(serial_number__iexact=q) | Q(asset__external_id=q))
            .select_related("customer")
            .order_by("hostname", "customer__code")[:10]
        )
        return Response(
            {
                "results": [
                    {
                        "asset_id": str(o.asset_id),
                        "hostname": o.hostname,
                        "customer_id": str(o.customer_id),
                        "customer_code": o.customer.code,
                        "customer_name": o.customer.name,
                        "site": o.site_name,
                        "group": o.group_name,
                        "os": o.os_name,
                        "last_seen_online": o.last_seen_online,
                    }
                    for o in rows
                ]
            }
        )

    @extend_schema(request=None, responses={202: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="refresh-details")
    def refresh_details(self, request: Request, pk: str | None = None) -> Response:
        """PERF-01: fetch this device's details (updates, policies, notifications, custom fields) on the next sync,
        even if they are recent, and start that sync. Needs the customer's sync permission; audited."""
        from apps.audit.services import record_event

        asset = Asset.objects.select_related("customer").filter(pk=_uuid(pk)).first()
        scope.get_customer_or_404(request.user, asset.customer_id if asset else None, Cap.CUSTOMER_SYNC, request)
        if asset is None:  # unreachable: get_customer_or_404 already raised; explicit for python -O
            raise NotFound()
        mapping = (
            CustomerSourceMapping.objects.filter(
                customer_id=asset.customer_id,
                integration_instance_id=asset.integration_instance_id,
                mapping_status="approved",
            )
            .select_related("integration_instance", "customer")
            .first()
        )
        if mapping is None:
            raise ValidationError({"detail": "This device's VSA X source is no longer approved for the customer."})
        Asset.objects.filter(pk=asset.pk).update(details_refresh_requested_at=timezone.now())
        try:
            run, _ = request_sync(mapping, requested_by=request.user)
        except SyncRefused as exc:
            raise ValidationError({"detail": str(exc), "code": exc.code}) from exc
        record_event(
            action="asset.details_refresh_requested",
            outcome="success",
            actor=request.user,
            customer=asset.customer,
            target_type="asset",
            target_id=str(asset.pk),
            request=request,
            metadata={"sync_run": str(run.id)},
        )
        return Response(
            {"sync_run_id": str(run.id), "state": run.state, "detail": "Details are fetched on this sync."},
            status=status.HTTP_202_ACCEPTED,
        )

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

    def get_customer(self) -> Any:
        self.customer_capability = (
            Cap.CUSTOMER_MANAGE_EXCEPTIONS if self.request.method == "POST" else Cap.CUSTOMER_READ
        )
        return super().get_customer()

    @extend_schema(
        description="Paginated onboarding device destinations, ranked by subnet evidence before naming hints.",
        parameters=[
            OpenApiParameter("instance", OpenApiTypes.UUID, required=True),
            OpenApiParameter("search", OpenApiTypes.STR, description="Hostname search, at most 100 characters."),
            OpenApiParameter("page", OpenApiTypes.INT),
            OpenApiParameter("page_size", OpenApiTypes.INT, description="At most 200 devices per page."),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get"])
    def suggestions(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        from collections import defaultdict

        from .group_suggestions import NOTE, SuggestionContext, onboarding
        from .models import GroupNode, IpAddressObservation

        customer = self.get_customer()
        instance = _uuid(request.query_params.get("instance"))
        group = (
            GroupNode.objects.filter(
                customer=customer,
                generation__in=current_generations(customer.id),
                generation__integration_instance_id=instance,
                external_id=pk,
            )
            .select_related("generation")
            .first()
        )
        if group is None:
            raise NotFound()
        if group.generation.published_at < stale_cutoff():
            raise ValidationError({"detail": "Source inventory is stale. Synchronize before reviewing suggestions."})
        enabled = onboarding(customer.id, instance, pk)
        search = serializers.CharField(required=False, allow_blank=True, max_length=100).run_validation(
            request.query_params.get("search", "")
        )
        members = (
            current_observations(customer.id)
            .filter(
                generation_id=group.generation_id,
                organization_external_id=group.organization_external_id,
                group_external_id=pk,
                hostname__icontains=search,
            )
            .order_by("hostname", "asset_id")
        )
        page = self.paginate_queryset(members if enabled else members.none())
        results = []
        if page:
            context = SuggestionContext(page[0])
            # Fetch the observation key with each address; no per-device queries.
            ips = IpAddressObservation.objects.filter(
                customer=customer, adapter__observation_id__in=[row.id for row in page]
            ).select_related("adapter")
            by_observation = defaultdict(list)
            for ip in ips:
                by_observation[ip.adapter.observation_id].append(ip)
            results = [
                {
                    "asset_id": str(row.asset_id),
                    "hostname": row.hostname,
                    **context.evaluate(row, by_observation[row.id]),
                }
                for row in page
            ]
        response = self.get_paginated_response(results)
        response.data.update({"is_onboarding": enabled, "suggestion_note": NOTE})
        return response

    PLAN_MAX_DEVICES = 2000

    @extend_schema(
        description="Onboarding devices grouped by their clearly best destination group (and site); ties and "
        "devices without evidence are listed separately. Hints only; nothing is moved.",
        parameters=[OpenApiParameter("instance", OpenApiTypes.UUID, required=True)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=True, methods=["get"], url_path="suggestions/plan")
    def suggestion_plan(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        from collections import defaultdict

        from .group_suggestions import NOTE, SuggestionContext, onboarding, plan
        from .models import GroupNode, IpAddressObservation

        customer = self.get_customer()
        instance = _uuid(request.query_params.get("instance"))
        group = (
            GroupNode.objects.filter(
                customer=customer,
                generation__in=current_generations(customer.id),
                generation__integration_instance_id=instance,
                external_id=pk,
            )
            .select_related("generation")
            .first()
        )
        if group is None:
            raise NotFound()
        if group.generation.published_at < stale_cutoff():
            raise ValidationError({"detail": "Source inventory is stale. Synchronize before reviewing suggestions."})
        if not onboarding(customer.id, instance, pk):
            return Response(
                {
                    "is_onboarding": False,
                    "destinations": [],
                    "ambiguous": [],
                    "unmatched": [],
                    "devices": 0,
                    "truncated": False,
                    "suggestion_note": NOTE,
                }
            )
        members = list(
            current_observations(customer.id)
            .filter(
                generation_id=group.generation_id,
                organization_external_id=group.organization_external_id,
                group_external_id=pk,
            )
            .order_by("hostname", "asset_id")[: self.PLAN_MAX_DEVICES + 1]
        )
        truncated = len(members) > self.PLAN_MAX_DEVICES
        members = members[: self.PLAN_MAX_DEVICES]
        if not members:
            return Response(
                {
                    "is_onboarding": True,
                    "destinations": [],
                    "ambiguous": [],
                    "unmatched": [],
                    "devices": 0,
                    "truncated": False,
                    "suggestion_note": NOTE,
                }
            )
        context = SuggestionContext(members[0])
        by_observation = defaultdict(list)
        for ip in IpAddressObservation.objects.filter(
            customer=customer, adapter__observation_id__in=[m.id for m in members]
        ).select_related("adapter"):
            by_observation[ip.adapter.observation_id].append(ip)
        result = plan(context, members, by_observation, context.site_names)
        return Response(
            {"is_onboarding": True, **result, "devices": len(members), "truncated": truncated, "suggestion_note": NOTE}
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get", "post"], url_path="settings")
    def group_settings(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        from apps.audit.services import record_event

        from .models import GroupNode, GroupSetting

        customer = self.get_customer()
        instance = _uuid(request.query_params.get("instance"))
        if not GroupNode.objects.filter(
            customer=customer,
            generation__in=current_generations(customer.id),
            generation__integration_instance_id=instance,
            external_id=pk,
        ).exists():
            raise NotFound()
        key = {"customer": customer, "integration_instance_id": instance, "group_external_id": pk}
        if request.method == "POST":

            class Input(serializers.Serializer):
                is_onboarding = serializers.BooleanField()

            data = Input(data=request.data)
            data.is_valid(raise_exception=True)
            obj, _ = GroupSetting.objects.update_or_create(**key, defaults=data.validated_data)
            record_event(
                action="group_setting.updated",
                outcome="success",
                actor=request.user,
                customer=customer,
                target_type="group_setting",
                target_id=str(obj.id),
                request=request,
                metadata={"is_onboarding": obj.is_onboarding, "instance": str(instance), "group": pk},
            )
        else:
            obj = GroupSetting.objects.filter(**key).first()
        return Response({"is_onboarding": obj.is_onboarding if obj else False})

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
