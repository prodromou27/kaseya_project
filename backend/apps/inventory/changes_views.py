"""VSA4-04 API: ``/customers/{id}/changes/`` — observed differences between two complete snapshots (read only)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.roles import Cap
from apps.customers.views import CustomerScopedMixin

from . import changes
from .models import AssetObservation

PAIR = [OpenApiParameter("from", str, description="Older generation ID"), OpenApiParameter("to", str)]


class CustomerChangesViewSet(CustomerScopedMixin, viewsets.GenericViewSet):
    customer_capability = Cap.CUSTOMER_READ
    queryset = AssetObservation.objects.none()

    def _diff(self, request: Request) -> dict[str, Any]:
        customer = self.get_customer()
        try:
            frm, to = changes.resolve_pair(
                customer.id, request.query_params.get("from"), request.query_params.get("to")
            )
        except changes.NotComparable as exc:
            raise ValidationError({"detail": exc.message}) from exc
        return changes.diff(customer.id, frm, to)

    @extend_schema(parameters=PAIR, responses={200: OpenApiTypes.OBJECT})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Summary counts for the pair (default: current vs previous complete snapshot)."""
        d = self._diff(request)
        d.pop("devices")
        return Response(d)

    @extend_schema(
        parameters=[*PAIR, OpenApiParameter("kind", str, enum=[*changes.KINDS]), OpenApiParameter("q", str)],
        responses={200: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"])
    def devices(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        rows = self._diff(request)["devices"]
        if (kind := request.query_params.get("kind")) and kind in changes.KINDS:
            rows = [r for r in rows if any(c["kind"] == kind for c in r["changes"])]
        if q := request.query_params.get("q", "").strip().casefold()[:100]:
            rows = [r for r in rows if q in r["hostname"].casefold()]
        page = self.paginate_queryset(rows)  # type: ignore[arg-type]
        return self.get_paginated_response(page)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["get"])
    def snapshots(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Complete snapshots of this customer that can be compared (newest first)."""
        return Response(
            [
                {
                    "id": str(g.pk),
                    "instance": g.integration_instance.name,
                    "published_at": g.published_at,
                    "state": g.state,
                    "is_current": g.is_current,
                    "row_count": g.row_count,
                    "data_basis": g.data_basis,
                }
                for g in changes.comparable_generations(self.get_customer().id)
            ]
        )
