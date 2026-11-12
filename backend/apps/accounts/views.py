from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponseRedirect
from django.middleware.csrf import get_token
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit.services import record_event
from apps.core.errors import error_body

from . import scope
from .authentication import SessionAuthentication401
from .middleware import AUTH_AT_SESSION_KEY
from .models import Role, User
from .oidc import OIDCClient, OIDCError, provision_user
from .permissions import IsSystemAdmin
from .serializers import LoginSerializer, RoleSerializer, UserSerializer, me_payload

logger = logging.getLogger("portal.auth")


def _start_session(request: Request, user: User, method: str) -> None:
    login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")  # rotates session key
    request.session[AUTH_AT_SESSION_KEY] = time.time()
    request.session["okp_auth_method"] = method


class AuthConfigView(APIView):
    """Public: which login methods are enabled. Also issues the CSRF cookie for the SPA."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    public_endpoint = True

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        get_token(request._request)
        return Response({"local_login_enabled": settings.LOCAL_LOGIN_ENABLED, "oidc_enabled": settings.OIDC["ENABLED"]})


class LocalLoginView(APIView):
    """Local password login — bootstrap/dev only (SECURITY.md §2). CSRF-protected and rate limited."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    public_endpoint = True

    @extend_schema(request=LoginSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        SessionAuthentication401().enforce_csrf(request)
        if not settings.LOCAL_LOGIN_ENABLED:
            raise PermissionDenied("Local login is disabled. Use single sign-on.")
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        user = authenticate(request._request, username=email, password=serializer.validated_data["password"])
        if user is None or user.auth_source != User.AuthSource.LOCAL:
            record_event(
                action="auth.login",
                outcome="failure",
                actor_label=email,
                target_type="user",
                request=request,
                metadata={"method": "local"},
            )
            return Response(
                error_body("invalid_credentials", "Invalid email or password."), status=status.HTTP_400_BAD_REQUEST
            )
        _start_session(request, user, "local")
        record_event(
            action="auth.login",
            outcome="success",
            actor=user,
            target_type="user",
            target_id=str(user.id),
            request=request,
            metadata={"method": "local"},
        )
        return Response(me_payload(user, scope.membership_capabilities(user)))


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        user = request.user
        record_event(action="auth.logout", outcome="success", actor=user, request=request)
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(me_payload(request.user, scope.membership_capabilities(request.user)))


class OIDCLoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    public_endpoint = True

    @extend_schema(responses={302: None})
    def get(self, request: Request) -> HttpResponseRedirect:
        if not settings.OIDC["ENABLED"]:
            raise PermissionDenied("Single sign-on is not configured.")
        try:
            url = OIDCClient(settings.OIDC).begin(request.session)
        except OIDCError as exc:
            logger.warning("oidc_begin_failed", extra={"oidc_error": exc.code})
            return HttpResponseRedirect("/login?error=sso_unavailable")
        return HttpResponseRedirect(url)


class OIDCCallbackView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
    public_endpoint = True

    @extend_schema(responses={302: None})
    def get(self, request: Request) -> HttpResponseRedirect:
        if not settings.OIDC["ENABLED"]:
            raise PermissionDenied("Single sign-on is not configured.")
        params: dict[str, Any] = {k: request.query_params.get(k, "") for k in ("code", "state", "error")}
        try:
            claims = OIDCClient(settings.OIDC).complete(request.session, params)
            user = provision_user(claims, settings.OIDC)
        except OIDCError as exc:
            record_event(
                action="auth.login",
                outcome="failure",
                target_type="user",
                request=request,
                metadata={"method": "oidc", "reason": exc.code},
            )
            return HttpResponseRedirect(f"/login?error={exc.code}")
        _start_session(request, user, "oidc")
        record_event(
            action="auth.login",
            outcome="success",
            actor=user,
            target_type="user",
            target_id=str(user.id),
            request=request,
            metadata={"method": "oidc", "amr": claims.get("amr")},
        )
        return HttpResponseRedirect(settings.OIDC["POST_LOGIN_REDIRECT"])


class RoleViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
    pagination_class = None


class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """System user administration (super admin only). Users are deactivated, never deleted (audit history)."""

    permission_classes = [IsSystemAdmin]
    serializer_class = UserSerializer
    queryset = User.objects.select_related("global_role").all()
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        search = self.request.query_params.get("search", "").strip()[:100]
        if search:
            qs = qs.filter(email__icontains=search)
        return qs

    def perform_create(self, serializer: UserSerializer) -> None:
        if not settings.LOCAL_LOGIN_ENABLED:
            raise ValidationError({"detail": "Local accounts are disabled; users are provisioned through SSO."})
        user = serializer.save()
        record_event(
            action="user.created",
            outcome="success",
            actor=self.request.user,
            target_type="user",
            target_id=str(user.id),
            request=self.request,
            metadata={"email": user.email, "global_role": user.global_role.key if user.global_role_id else None},
        )

    def perform_update(self, serializer: UserSerializer) -> None:
        target: User = serializer.instance
        changes = {k: v for k, v in serializer.validated_data.items() if k != "password"}
        if target.pk == self.request.user.pk and (
            changes.get("is_active") is False or ("global_role" in changes and changes["global_role"] is None)
        ):
            raise ValidationError({"detail": "You cannot deactivate or demote your own account."})
        user = serializer.save()
        scope.invalidate_cache(user)
        record_event(
            action="user.updated",
            outcome="success",
            actor=self.request.user,
            target_type="user",
            target_id=str(user.id),
            request=self.request,
            metadata={
                "changed": sorted(changes.keys()) + (["password"] if "password" in serializer.validated_data else []),
                "is_active": user.is_active,
                "global_role": user.global_role.key if user.global_role_id else None,
            },
        )
