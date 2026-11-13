from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import Cap
from apps.audit.services import record_event

from .models import ConnectorHost, IntegrationInstance, SyncQuarantine, SyncSchedule
from .providers import PROVIDERS, validate_fields
from .secrets import CredentialStorageUnavailable, credential_source, encrypt_fields, storage_available


class CredentialSerializer(serializers.Serializer):
    """Write-only credential fields for the integration's provider (see ``GET /integrations/providers/``).

    All values are encrypted together; they are never echoed back, logged or audited.
    """

    fields = serializers.DictField(child=serializers.CharField(allow_blank=True, max_length=1000), write_only=True)


class IntegrationInstanceSerializer(serializers.ModelSerializer):
    """``credential_ref`` is write-only: responses only say whether one is configured."""

    credential_ref = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=200)
    credential_configured = serializers.SerializerMethodField()
    credential_source = serializers.SerializerMethodField()
    credential_set_by = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationInstance
        fields = [
            "id",
            "name",
            "provider",
            "base_url",
            "region",
            "credential_ref",
            "credential_configured",
            "credential_source",
            "credential_set_at",
            "credential_set_by",
            "enabled",
            "installed_updates_budget",
            "applied_policies_budget",
            "notifications_budget",
            "custom_fields_budget",
            "last_test_at",
            "last_test_outcome",
            "last_test_result",
            "verify_tls",
            "max_rps",
            "status",
            "is_fixture",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "verify_tls",
            "status",
            "created_at",
            "updated_at",
            "credential_configured",
            "credential_set_at",
        ]

    def get_credential_configured(self, obj: IntegrationInstance) -> bool:
        return bool(obj.credential_ref or obj.credential_ciphertext)

    def get_credential_source(self, obj: IntegrationInstance) -> str:
        """``portal`` (entered in the portal, encrypted), ``server`` (env/file reference) or ``none``."""
        return credential_source(obj)

    def get_credential_set_by(self, obj: IntegrationInstance) -> str | None:
        return obj.credential_set_by.email if obj.credential_set_by_id else None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        instance = self.instance or IntegrationInstance()
        if self.instance is not None and "provider" in attrs and attrs["provider"] != self.instance.provider:
            raise ValidationError({"provider": "Provider cannot be changed after creation."})
        if self.instance is not None and "is_fixture" in attrs and attrs["is_fixture"] != self.instance.is_fixture:
            raise ValidationError({"is_fixture": "Fixture/live designation cannot be changed after creation."})
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
        attrs["base_url"] = instance.base_url
        return attrs


class IntegrationInstanceViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Global connector configuration (super admin). No delete: disable instead; mappings reference it."""

    serializer_class = IntegrationInstanceSerializer
    # DELETE exists only for the ``credential`` action; there is no destroy mixin (disable instead).
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    queryset = IntegrationInstance.objects.select_related("credential_set_by")

    def get_permissions(self) -> list[Any]:
        if self.action == "options_list":
            return [IsAuthenticated()]
        return [IsSystemAdmin()]

    def get_queryset(self) -> QuerySet[IntegrationInstance]:
        return IntegrationInstance.objects.select_related("credential_set_by")

    def perform_create(self, serializer: IntegrationInstanceSerializer) -> None:
        inst = serializer.save()
        record_event(
            action="integration.created",
            outcome="success",
            actor=self.request.user,
            target_type="integration",
            target_id=str(inst.id),
            request=self.request,
            metadata={"provider": inst.provider, "base_url": inst.base_url, "is_fixture": inst.is_fixture},
        )

    def perform_update(self, serializer: IntegrationInstanceSerializer) -> None:
        changed = sorted(serializer.validated_data.keys())
        # From the DB: ``validate()`` has already applied the new values to ``serializer.instance``.
        old_url = IntegrationInstance.objects.values_list("base_url", flat=True).get(pk=serializer.instance.pk)
        inst = serializer.save()
        if inst.base_url != old_url and inst.credential_ciphertext:
            # Never send a token entered for one server to another: the admin must enter it again.
            _clear_portal_credential(inst)
            record_event(
                action="integration.credential_cleared",
                outcome="success",
                actor=self.request.user,
                target_type="integration",
                target_id=str(inst.id),
                request=self.request,
                metadata={"reason": "base_url_changed"},
            )
        record_event(
            action="integration.updated",
            outcome="success",
            actor=self.request.user,
            target_type="integration",
            target_id=str(inst.id),
            request=self.request,
            metadata={"changed": changed, "enabled": inst.enabled, "base_url": inst.base_url},
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get"])
    def organizations(self, request: Request, pk: str | None = None) -> Response:
        """Live (or fixture) list of source organisations with their mapping status. One read-only API crawl."""
        instance = self.get_object()
        record_event(
            action="integration.discovery",
            outcome="success",
            actor=request.user,
            target_type="integration",
            target_id=str(instance.id),
            request=request,
        )
        return _discover_organizations(instance)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request: Request, pk: str | None = None) -> Response:
        """VSA1-01: one read-only ``GET /api/v3/ratelimits``. Records outcome, latency and reported limits only."""
        instance = self.get_object()
        result = _test_connection(instance)
        instance.last_test_at = timezone.now()
        instance.last_test_outcome = result["outcome"]
        instance.last_test_result = result
        instance.save(update_fields=["last_test_at", "last_test_outcome", "last_test_result"])
        record_event(
            action="integration.connection_test",
            outcome="success" if result["outcome"] == "ok" else "failure",
            actor=request.user,
            target_type="integration",
            target_id=str(instance.id),
            request=request,
            metadata={
                "outcome": result["outcome"],
                "latency_ms": result.get("latency_ms"),
                "status": result.get("http_status"),
            },
        )
        return Response({**result, "tested_at": instance.last_test_at})

    @extend_schema(request=CredentialSerializer, responses={200: IntegrationInstanceSerializer})
    @action(detail=True, methods=["post", "delete"], url_path="credential")
    def credential(self, request: Request, pk: str | None = None) -> Response:
        """Set (POST) or remove (DELETE) the API token entered in the portal. Write-only; super admin only."""
        instance = self.get_object()
        if request.method == "DELETE":
            had = bool(instance.credential_ciphertext)
            _clear_portal_credential(instance)
            record_event(
                action="integration.credential_cleared",
                outcome="success",
                actor=request.user,
                target_type="integration",
                target_id=str(instance.id),
                request=request,
                metadata={"reason": "admin_removed", "had_credential": had},
            )
            return Response(self.get_serializer(instance).data)
        if instance.is_fixture:
            raise ValidationError({"detail": "Fixture instances never use credentials."})
        body = CredentialSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        clean, errors = validate_fields(instance.provider, body.validated_data["fields"])
        if errors:
            raise ValidationError(errors)
        try:
            ciphertext = encrypt_fields(instance, clean)
        except CredentialStorageUnavailable as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        replaced = bool(instance.credential_ciphertext)
        instance.credential_ciphertext = ciphertext
        instance.credential_set_at = timezone.now()
        instance.credential_set_by = request.user
        # The previous connection test was for the old credential.
        instance.last_test_at, instance.last_test_outcome, instance.last_test_result = None, "", {}
        instance.save(update_fields=[*_CREDENTIAL_FIELDS])
        record_event(
            action="integration.credential_set",
            outcome="success",
            actor=request.user,
            target_type="integration",
            target_id=str(instance.id),
            request=request,
            metadata={"replaced": replaced, "server_reference_also_set": bool(instance.credential_ref)},
        )
        return Response(self.get_serializer(instance).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="providers")
    def providers(self, request: Request) -> Response:
        """Provider catalog: which integrations exist and what an administrator must enter for each."""
        return Response([spec.as_dict() for spec in PROVIDERS.values()])

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="credential-storage")
    def credential_storage(self, request: Request) -> Response:
        """Whether this server can store portal-entered credentials (an encryption key is configured)."""
        return Response({"available": storage_available()})

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"], url_path="options")
    def options_list(self, request: Request) -> Response:
        """Minimal id/name/provider list for users who may propose source mappings."""
        user = request.user
        ids = scope.accessible_customer_ids(user, Cap.CUSTOMER_PROPOSE_MAPPINGS)
        if ids is not None and not ids:
            raise PermissionDenied()
        data = [
            {"id": str(i.id), "name": i.name, "provider": i.provider, "is_fixture": i.is_fixture}
            for i in IntegrationInstance.objects.order_by("provider", "name")
        ]
        return Response(data)


_CREDENTIAL_FIELDS = (
    "credential_ciphertext",
    "credential_set_at",
    "credential_set_by",
    "last_test_at",
    "last_test_outcome",
    "last_test_result",
    "updated_at",
)


def _clear_portal_credential(instance: IntegrationInstance) -> None:
    instance.credential_ciphertext = ""
    instance.credential_set_at = None
    instance.credential_set_by = None
    instance.last_test_at, instance.last_test_outcome, instance.last_test_result = None, "", {}
    instance.save(update_fields=[*_CREDENTIAL_FIELDS])


class SyncQuarantineSerializer(serializers.ModelSerializer):
    integration = serializers.CharField(source="integration_instance.name", read_only=True)

    class Meta:
        model = SyncQuarantine
        fields = [
            "id",
            "sync_run",
            "integration",
            "external_id",
            "external_org_id",
            "reason",
            "snapshot",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = fields


class SyncQuarantineViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Quarantined source records — cross-customer by nature, therefore super admin only."""

    permission_classes = [IsSystemAdmin]
    serializer_class = SyncQuarantineSerializer
    queryset = SyncQuarantine.objects.select_related("integration_instance").all()

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        reason = self.request.query_params.get("reason", "").strip()[:64]
        return qs.filter(reason=reason) if reason else qs


_TEST_MESSAGES = {
    "ok": "Connected. The token can read the rate-limit endpoint.",
    "auth_failed": "The VSA X server rejected the credentials (401/403). Check the token reference; not retried.",
    "rate_limited": "The VSA X server reported the rate limit is exhausted (429). Try again after the reset time.",
    "vendor_unavailable": "The VSA X server did not respond or returned a server error.",
    "egress_blocked": "The host is not on the deployment allowlist, resolves to a blocked address, or redirected.",
    "endpoint_not_allowed": "The request path is not on the read-only allowlist.",
    "credential_unavailable": "No usable API token: enter it with 'Set API token', or check the server "
    "credential reference.",
    "bad_response": "The server answered, but not with the documented rate-limit response.",
    "vendor_client_error": "The server rejected the request (4xx).",
}


def _test_connection(instance: IntegrationInstance) -> dict[str, Any]:
    import time

    from .http import ConnectorError
    from .secrets import CredentialUnavailable
    from .vsa.adapter import VsaXAdapter
    from .vsa.schema import RecordInvalid, normalize_rate_limits

    if instance.provider != IntegrationInstance.Provider.VSA_X:
        raise ValidationError({"detail": "Connection tests are implemented for VSA X only."})
    started = time.monotonic()
    out: dict[str, Any] = {"data_basis": "fixture" if instance.is_fixture else "live"}
    try:
        limits = normalize_rate_limits(VsaXAdapter(instance).get_rate_limits())
        out.update(outcome="ok", **limits)
    except CredentialUnavailable:
        out["outcome"] = "credential_unavailable"
    except RecordInvalid:
        out["outcome"] = "bad_response"
    except ConnectorError as exc:
        out["outcome"] = exc.code
        out["http_status"] = exc.status
        if exc.retry_after is not None:
            out["retry_after_seconds"] = exc.retry_after
    out["latency_ms"] = round((time.monotonic() - started) * 1000)
    out["message"] = _TEST_MESSAGES.get(out["outcome"], "The connection test failed.")
    return out


def _discover_organizations(instance: IntegrationInstance) -> Response:
    from apps.customers.models import CustomerSourceMapping

    from .http import ConnectorError
    from .secrets import CredentialUnavailable
    from .vsa.adapter import VsaXAdapter
    from .vsa.schema import PageInvalid

    if instance.provider != IntegrationInstance.Provider.VSA_X:
        raise ValidationError({"detail": "Organisation discovery is implemented for VSA X only."})
    try:
        orgs, invalid = VsaXAdapter(instance).list_organizations()
    except (ConnectorError, CredentialUnavailable, PageInvalid) as exc:
        code = getattr(exc, "code", "credential_unavailable" if isinstance(exc, CredentialUnavailable) else "bad_page")
        raise ValidationError({"detail": f"Discovery failed: {code}."}) from exc
    mappings = {
        m.external_org_id: m
        for m in CustomerSourceMapping.objects.filter(
            integration_instance=instance, mapping_status__in=["proposed", "approved"]
        ).select_related("customer")
    }
    return Response(
        {
            "data_basis": "fixture" if instance.is_fixture else "live",
            "invalid_records": len(invalid),
            "organizations": [
                {
                    "external_org_id": o.id,
                    "name": o.name,
                    "type": o.type,
                    "mapping": None
                    if o.id not in mappings
                    else {
                        "id": str(mappings[o.id].id),
                        "status": mappings[o.id].mapping_status,
                        "customer": {"id": str(mappings[o.id].customer_id), "code": mappings[o.id].customer.code},
                    },
                }
                for o in orgs
            ],
        }
    )


class SyncScheduleSerializer(serializers.ModelSerializer):
    customer = serializers.SerializerMethodField()
    integration = serializers.CharField(source="mapping.integration_instance.name", read_only=True)
    external_org_id = serializers.CharField(source="mapping.external_org_id", read_only=True)

    class Meta:
        model = SyncSchedule
        fields = [
            "id",
            "mapping",
            "customer",
            "integration",
            "external_org_id",
            "interval_hours",
            "enabled",
            "next_run_at",
            "last_run_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "customer",
            "integration",
            "external_org_id",
            "next_run_at",
            "last_run_at",
            "created_at",
        ]

    def get_customer(self, obj: SyncSchedule) -> dict[str, str]:
        return {"id": str(obj.mapping.customer_id), "code": obj.mapping.customer.code}

    def validate_mapping(self, value: Any) -> Any:
        if value.mapping_status != "approved":
            raise ValidationError("Only approved mappings can be scheduled.")
        return value


class SyncScheduleViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Scheduled read-only collection (super admin). Dispatched by Celery Beat."""

    permission_classes = [IsSystemAdmin]
    serializer_class = SyncScheduleSerializer
    queryset = SyncSchedule.objects.select_related("mapping", "mapping__customer", "mapping__integration_instance")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_create(self, serializer: SyncScheduleSerializer) -> None:
        from django.utils import timezone

        s = serializer.save(next_run_at=timezone.now())
        record_event(
            action="sync.schedule_saved",
            outcome="success",
            actor=self.request.user,
            customer=s.mapping.customer,
            target_type="sync_schedule",
            target_id=str(s.id),
            request=self.request,
            metadata={"interval_hours": s.interval_hours},
        )

    def perform_update(self, serializer: SyncScheduleSerializer) -> None:
        s = serializer.save()
        record_event(
            action="sync.schedule_saved",
            outcome="success",
            actor=self.request.user,
            customer=s.mapping.customer,
            target_type="sync_schedule",
            target_id=str(s.id),
            request=self.request,
            metadata={"interval_hours": s.interval_hours, "enabled": s.enabled},
        )


class ConnectorHostSerializer(serializers.ModelSerializer):
    added_by = serializers.SerializerMethodField()

    class Meta:
        model = ConnectorHost
        fields = ["id", "provider", "hostname", "reason", "added_by", "created_at"]
        read_only_fields = ["id", "added_by", "created_at"]

    def get_added_by(self, obj: ConnectorHost) -> str | None:
        return obj.added_by.email if obj.added_by_id else None

    def validate_hostname(self, value: str) -> str:
        from .urlpolicy import normalize_api_hostname

        try:
            return normalize_api_hostname(value)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages) from exc

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["provider"] != IntegrationInstance.Provider.VSA_X:
            raise ValidationError({"provider": "Only VSA X is supported in this phase."})
        if ConnectorHost.objects.filter(provider=attrs["provider"], hostname=attrs["hostname"]).exists():
            raise ValidationError({"hostname": "This host is already allowed."})
        return attrs


class ConnectorHostViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Connector egress allowlist managed in the portal (super admin). Deployment-configured hosts are listed too."""

    permission_classes = [IsSystemAdmin]
    serializer_class = ConnectorHostSerializer
    queryset = ConnectorHost.objects.select_related("added_by")
    pagination_class = None

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from django.conf import settings

        rows = self.get_serializer(self.get_queryset(), many=True).data
        deployment = [
            {"provider": provider, "hostname": host.lower()}
            for provider, hosts in settings.CONNECTOR_ALLOWED_HOSTS.items()
            for host in hosts
        ]
        return Response({"results": rows, "deployment": deployment})

    def perform_create(self, serializer: ConnectorHostSerializer) -> None:
        row = serializer.save(added_by=self.request.user)
        record_event(
            action="integration.host_allowed",
            outcome="success",
            actor=self.request.user,
            target_type="connector_host",
            target_id=str(row.id),
            request=self.request,
            metadata={"provider": row.provider, "hostname": row.hostname, "reason": row.reason[:200]},
        )

    def perform_destroy(self, instance: ConnectorHost) -> None:
        from django.conf import settings

        deployment_hosts = {h.lower() for h in settings.CONNECTOR_ALLOWED_HOSTS.get(instance.provider, [])}
        in_deployment = instance.hostname in deployment_hosts
        users = [
            i.name
            for i in IntegrationInstance.objects.filter(provider=instance.provider, is_fixture=False)
            if (i.base_url or "").lower().removeprefix("https://").rstrip("/") == instance.hostname
        ]
        if users and not in_deployment:
            raise ValidationError(
                {"detail": f"Still used by: {', '.join(sorted(users))}. Change or disable those integrations first."}
            )
        record_event(
            action="integration.host_removed",
            outcome="success",
            actor=self.request.user,
            target_type="connector_host",
            target_id=str(instance.id),
            request=self.request,
            metadata={"provider": instance.provider, "hostname": instance.hostname},
        )
        instance.delete()
