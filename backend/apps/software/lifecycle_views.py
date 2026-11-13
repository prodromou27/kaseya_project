"""VSA4-05 lifecycle catalog API (super admins, two-person review) and the customer lifecycle view."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsSystemAdmin
from apps.accounts.roles import Cap
from apps.audit.services import record_event
from apps.customers.views import CustomerScopedMixin

from . import lifecycle
from .catalog import check_reviewer
from .models import LifecycleEntry, SoftwareProduct

SOURCE_TYPES = ["vendor_lifecycle_page", "vendor_announcement", "manual_verification"]
MAX_BULK = 200


class LifecycleEntrySerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    reviewed_by = serializers.SlugRelatedField(slug_field="email", read_only=True)
    product = serializers.PrimaryKeyRelatedField(
        queryset=SoftwareProduct.objects.all(), required=False, allow_null=True
    )
    product_label = serializers.SerializerMethodField()
    source_type = serializers.ChoiceField(choices=SOURCE_TYPES)

    class Meta:
        model = LifecycleEntry
        fields = [
            "id",
            "kind",
            "os_family",
            "product",
            "product_label",
            "release_label",
            "version_prefix",
            "edition_note",
            "release_date",
            "end_of_mainstream",
            "end_of_support",
            "extended_until",
            "source_url",
            "source_type",
            "source_checked_at",
            "confidence",
            "note",
            "state",
            "created_by",
            "created_at",
            "reviewed_by",
            "reviewed_at",
            "review_note",
        ]
        read_only_fields = ["id", "state", "created_by", "created_at", "reviewed_by", "reviewed_at", "review_note"]

    def get_product_label(self, obj: LifecycleEntry) -> str | None:
        return str(obj.product) if obj.product_id else None

    def validate_source_url(self, value: str) -> str:
        if not value.startswith("https://"):
            raise ValidationError("Evidence URL must be https.")
        return value

    def validate_version_prefix(self, value: str) -> str:
        value = (value or "").strip()
        if value and lifecycle.version_parts(value) is None:
            raise ValidationError("Use a dotted numeric prefix such as 10.0.22631 or 115.")
        if value and not all(p.isdigit() for p in value.split(".")):
            raise ValidationError("Only digits and dots.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        kind = attrs.get("kind")
        attrs["os_family"] = (attrs.get("os_family") or "").strip()
        if kind == LifecycleEntry.Kind.OS:
            if len(attrs["os_family"]) < 4:
                raise ValidationError({"os_family": "Give the OS family as reported, e.g. 'Windows 11'."})
            if attrs.get("product"):
                raise ValidationError({"product": "OS entries do not reference a software product."})
        elif kind == LifecycleEntry.Kind.SOFTWARE:
            if not attrs.get("product"):
                raise ValidationError({"product": "Choose the reviewed catalog product."})
            if attrs["os_family"]:
                raise ValidationError({"os_family": "Software entries do not use an OS family."})
        if attrs["source_checked_at"] > timezone.localdate():
            raise ValidationError({"source_checked_at": "Cannot be in the future."})
        order = [attrs.get("release_date"), attrs.get("end_of_mainstream"), attrs.get("end_of_support")]
        known = [d for d in order if d]
        if known != sorted(known):
            raise ValidationError({"end_of_support": "Dates must be in order: release ≤ mainstream end ≤ support end."})
        if attrs.get("extended_until") and attrs["extended_until"] < attrs["end_of_support"]:
            raise ValidationError({"extended_until": "Extended support cannot end before standard support."})
        return attrs


class LifecycleEntryViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Lifecycle catalog. Proposed by one super admin, approved by a different one; approved rows are immutable."""

    permission_classes = [IsSystemAdmin]
    serializer_class = LifecycleEntrySerializer

    def get_queryset(self) -> QuerySet[LifecycleEntry]:
        qs = LifecycleEntry.objects.select_related("created_by", "reviewed_by", "product")
        state = self.request.query_params.get("state", "").strip()[:12]
        return qs.filter(state=state) if state else qs

    def _audit(self, name: str, entry: LifecycleEntry, **extra: Any) -> None:
        record_event(
            action=f"lifecycle.{name}",
            outcome="success",
            actor=self.request.user,
            target_type="lifecycle_entry",
            target_id=str(entry.id),
            request=self.request,
            metadata={
                "kind": entry.kind,
                "target": entry.os_family or str(entry.product_id),
                "release": entry.release_label,
                "end_of_support": entry.end_of_support.isoformat(),
                "confidence": entry.confidence,
                **extra,
            },
        )

    def perform_create(self, serializer: LifecycleEntrySerializer) -> None:
        entry = serializer.save(created_by=self.request.user)
        self._audit("proposed", entry)

    @extend_schema(request=LifecycleEntrySerializer(many=True), responses={201: LifecycleEntrySerializer(many=True)})
    @action(detail=False, methods=["post"])
    def bulk(self, request: Request) -> Response:
        """Propose many entries at once (e.g. from a spreadsheet the UI parsed). All-or-nothing."""
        rows = request.data.get("rows") if isinstance(request.data, dict) else request.data
        if not isinstance(rows, list) or not rows:
            raise ValidationError({"rows": "Provide a non-empty list of entries."})
        if len(rows) > MAX_BULK:
            raise ValidationError({"rows": f"At most {MAX_BULK} entries per request."})
        s = LifecycleEntrySerializer(data=rows, many=True)
        if not s.is_valid():
            raise ValidationError({"rows": s.errors})
        with transaction.atomic():
            entries = s.save(created_by=request.user)
        for e in entries:
            self._audit("proposed", e, bulk=True)
        return Response(LifecycleEntrySerializer(entries, many=True).data, status=status.HTTP_201_CREATED)

    def _transition(self, pk: str | None, *, to: str, allowed_from: tuple[str, ...]) -> LifecycleEntry:
        with transaction.atomic():
            entry = LifecycleEntry.objects.select_for_update().get(pk=self.get_object().pk)
            if entry.state not in allowed_from:
                raise ValidationError({"state": f"Entry is {entry.state}."})
            if to in (LifecycleEntry.State.APPROVED, LifecycleEntry.State.REJECTED):
                check_reviewer(entry.created_by_id, self.request.user)
                entry.reviewed_by, entry.reviewed_at = self.request.user, timezone.now()
            entry.state = to
            entry.review_note = (
                str(self.request.data.get("note", ""))[:2000] if isinstance(self.request.data, dict) else ""
            )
            entry.save()
        return entry

    @extend_schema(request=None, responses={200: LifecycleEntrySerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str | None = None) -> Response:
        entry = self._transition(pk, to=LifecycleEntry.State.APPROVED, allowed_from=(LifecycleEntry.State.PROPOSED,))
        self._audit("approved", entry)
        return Response(LifecycleEntrySerializer(entry).data)

    @extend_schema(request=None, responses={200: LifecycleEntrySerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str | None = None) -> Response:
        entry = self._transition(pk, to=LifecycleEntry.State.REJECTED, allowed_from=(LifecycleEntry.State.PROPOSED,))
        self._audit("rejected", entry)
        return Response(LifecycleEntrySerializer(entry).data)

    @extend_schema(request=None, responses={200: LifecycleEntrySerializer})
    @action(detail=True, methods=["post"])
    def retire(self, request: Request, pk: str | None = None) -> Response:
        """Stop using an approved entry (e.g. superseded). It stays as evidence; propose a corrected one."""
        entry = self._transition(pk, to=LifecycleEntry.State.RETIRED, allowed_from=(LifecycleEntry.State.APPROVED,))
        self._audit("retired", entry)
        return Response(LifecycleEntrySerializer(entry).data)


def _on_date(request: Request) -> dt.date:
    raw = request.query_params.get("on", "").strip()
    if not raw:
        return timezone.localdate()
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError({"on": "Use YYYY-MM-DD."}) from exc


class CustomerLifecycleViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    """``/customers/{id}/lifecycle/`` - OS and software support status of the latest snapshot."""

    customer_capability = Cap.CUSTOMER_READ

    @extend_schema(
        parameters=[OpenApiParameter("on", str, description="Evaluate on this date (YYYY-MM-DD); default today")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(lifecycle.summary(self.get_customer().id, _on_date(request)))

    @extend_schema(
        parameters=[
            OpenApiParameter("on", str),
            OpenApiParameter("kind", str, enum=["os", "software"]),
            OpenApiParameter("status", str, enum=[*lifecycle.STATUSES]),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def devices(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Per-device (OS) or per-installation (software) rows, filtered by status."""
        on = _on_date(request)
        kind = request.query_params.get("kind", "os")
        wanted = request.query_params.get("status", "")
        if kind not in ("os", "software") or (wanted and wanted not in lifecycle.STATUSES):
            raise ValidationError({"detail": "Unknown kind or status."})
        customer_id = self.get_customer().id
        rows = lifecycle.os_rows(customer_id, on) if kind == "os" else lifecycle.software_rows(customer_id, on)
        if wanted:
            rows = [r for r in rows if r["status"] == wanted]
        return Response({"evaluated_on": on, "kind": kind, "count": len(rows), "results": rows[:2000]})
