from __future__ import annotations

import time
from collections.abc import Callable

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse

AUTH_AT_SESSION_KEY = "okp_auth_at"


class SessionTimeoutMiddleware:
    """Absolute session lifetime. Idle timeout is SESSION_COOKIE_AGE + SESSION_SAVE_EVERY_REQUEST."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            auth_at = request.session.get(AUTH_AT_SESSION_KEY)
            if not isinstance(auth_at, int | float) or (
                time.time() - auth_at > settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS
            ):
                from apps.audit.services import record_event

                record_event(action="auth.session_expired", outcome="success", actor=user, request=request)
                logout(request)
        return self.get_response(request)
