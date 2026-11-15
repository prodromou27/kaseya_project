"""Unauthenticated health probes. They expose no customer data and no dependency details."""

from __future__ import annotations

from django.db import connection
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsSystemAdmin


class LivenessView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    public_endpoint = True

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class ReadinessView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    public_endpoint = True

    @extend_schema(responses={200: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            return Response({"status": "unavailable", "checks": {"database": "fail"}}, status=503)
        return Response({"status": "ok", "checks": {"database": "ok"}})


class SystemStatusView(APIView):
    """``GET /api/v1/system/status/`` — operational findings for super administrators (no vendor calls)."""

    permission_classes = [IsSystemAdmin]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        from .system_status import collect

        return Response(collect(check_worker=request.query_params.get("worker", "1") != "0"))
