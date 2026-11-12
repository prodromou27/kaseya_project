"""Standard API error envelope.

Every API error is returned as::

    {"error": {"code": "not_found", "message": "...", "details": {...}, "request_id": "..."}}

Unexpected exceptions never leak stack traces, SQL or vendor response bodies to clients.
"""

from __future__ import annotations

import logging
from typing import Any

from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .redaction import redact
from .request_context import get_request_id

logger = logging.getLogger("portal.errors")


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": get_request_id()}
    if details:
        body["details"] = redact(details)
    return {"error": body}


def _record_denial(context: dict[str, Any], code: str) -> None:
    request = context.get("request")
    if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
        return
    from apps.audit.services import record_event  # local import: audit depends on core

    record_event(
        action="authz.denied",
        actor=request.user,
        outcome="denied",
        target_type="endpoint",
        target_id=request.path[:200],
        request=request,
        metadata={"method": request.method, "reason": code},
    )


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    response = exception_handler(exc, context)
    if response is None:
        logger.exception("unhandled_api_exception", extra={"view": str(context.get("view"))})
        return Response(
            error_body("server_error", "An unexpected error occurred."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, exceptions.ValidationError):
        code, message, details = "validation_error", "The request was invalid.", exc.detail
    elif isinstance(exc, exceptions.APIException):
        code = exc.get_codes() if isinstance(exc.get_codes(), str) else exc.default_code
        detail = exc.detail
        message = str(detail) if isinstance(detail, str) else str(exc.default_detail)
        details = None if isinstance(detail, str) else detail
    else:  # pragma: no cover - DRF only handles APIException/Http404/PermissionDenied
        code, message, details = "error", "Request failed.", None

    if response.status_code == status.HTTP_403_FORBIDDEN:
        _record_denial(context, str(code))

    response.data = error_body(str(code), message, details)
    return response


def json_404(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return JsonResponse(error_body("not_found", "Not found."), status=404)


def json_500(request: HttpRequest) -> JsonResponse:
    return JsonResponse(error_body("server_error", "An unexpected error occurred."), status=500)
