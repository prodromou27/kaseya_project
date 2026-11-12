"""P0-07: append-only audit, redaction (SEC-03), request IDs, standard error envelope."""

from __future__ import annotations

import io
import json
import logging

import pytest
from django.db import DatabaseError, connection, transaction
from rest_framework import exceptions
from rest_framework.test import APIClient

from apps.audit.models import AppendOnlyError, AuditEvent
from apps.audit.services import record_event
from apps.core.errors import api_exception_handler
from apps.core.logging import JsonFormatter, RedactingFilter, RequestIdFilter
from apps.core.redaction import REDACTED, redact, redact_text

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- append-only


def test_audit_event_cannot_be_modified_or_deleted_via_orm(world):
    event = record_event(action="x.y", outcome="success", customer=world.customer_a)
    event.action = "tampered"
    with pytest.raises(AppendOnlyError):
        event.save()
    with pytest.raises(AppendOnlyError):
        event.delete()
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.filter(pk=event.pk).update(action="tampered")
    with pytest.raises(AppendOnlyError):
        AuditEvent.objects.filter(pk=event.pk).delete()


@pytest.mark.parametrize("sql", ["UPDATE audit_auditevent SET action = 'tampered'", "DELETE FROM audit_auditevent"])
def test_audit_append_only_enforced_by_postgres_trigger(world, sql):
    record_event(action="x.y", outcome="success")
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cur:
        cur.execute(sql)
    assert AuditEvent.objects.filter(action="x.y").exists()


def test_audit_api_is_read_only(world):
    client = world.client(world.super_admin)
    assert client.get("/api/v1/audit-events/").status_code == 200
    event = record_event(action="x.y", outcome="success")
    assert client.post("/api/v1/audit-events/", {"action": "fake"}).status_code == 405
    assert client.delete(f"/api/v1/audit-events/{event.id}/").status_code in (404, 405)


def test_audit_event_captures_request_id_and_ip(world):
    client = world.client(world.engineer_a)
    resp = client.get(f"/api/v1/customers/{world.customer_b.id}/", HTTP_X_REQUEST_ID="req-abcdef123456")
    event = AuditEvent.objects.get(action="authz.denied")
    assert event.request_id == "req-abcdef123456" == resp["X-Request-ID"]
    assert event.source_ip == "127.0.0.1"


# ---------------------------------------------------------------- redaction (SEC-03)


SECRET_SAMPLES = [
    "Authorization: Basic dG9rZW5JZDp0b2tlblNlY3JldA==",
    "Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLXZhbHVl",
    "vendor said: invalid api_key=sk_live_ABCDEF123456",
    "x-api-key: ITG.abcdef0123456789",
    "connect https://admin:hunter2pass@vsa.example.com/api failed",
    'payload {"password": "P@ssw0rd!", "user": "x"}',
]


@pytest.mark.parametrize("sample", SECRET_SAMPLES)
def test_redact_text_scrubs_secret_values(sample):
    out = redact_text(sample)
    for secret in (
        "dG9rZW5JZDp0b2tlblNlY3JldA",
        "c2lnbmF0dXJlLXZhbHVl",
        "sk_live_ABCDEF123456",
        "ITG.abcdef0123456789",
        "hunter2pass",
        "P@ssw0rd!",
    ):
        assert secret not in out
    assert REDACTED in out


def test_redact_nested_mapping_keys():
    data = {"user": "a", "token": "abc", "nested": {"client_secret": "s", "items": [{"Authorization": "x"}]}}
    out = redact(data)
    assert out == {
        "user": "a",
        "token": REDACTED,
        "nested": {"client_secret": REDACTED, "items": [{"Authorization": REDACTED}]},
    }


def test_audit_metadata_is_redacted(world):
    event = record_event(action="x", outcome="failure", metadata={"api_key": "k-123", "detail": "Bearer abcdefghijkl"})
    assert event.metadata == {"api_key": REDACTED, "detail": f"Bearer {REDACTED}"}


def _render(record_kwargs: dict, msg: str, *args: object, exc: BaseException | None = None) -> dict:
    logger = logging.getLogger("test.redaction")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    try:
        if exc is not None:
            try:
                raise exc
            except BaseException:
                logger.exception(msg, *args, extra=record_kwargs)
        else:
            logger.warning(msg, *args, extra=record_kwargs)
    finally:
        logger.removeHandler(handler)
    return json.loads(stream.getvalue())


def test_logs_redact_message_args_extras_and_exceptions():
    out = _render(
        {"vendor_headers": {"Authorization": "Basic Zm9vOmJhcg=="}, "secret_ref": "abc"},
        "vendor error %s",
        "token=supersecretvalue1",
        exc=RuntimeError("connect https://u:p4ssw0rd@host failed; api_key=XYZ987654"),
    )
    text = json.dumps(out)
    for secret in ("supersecretvalue1", "Zm9vOmJhcg", "p4ssw0rd", "XYZ987654"):
        assert secret not in text
    assert out["vendor_headers"]["Authorization"] == REDACTED
    assert out["secret_ref"] == REDACTED


# ---------------------------------------------------------------- request ids & error envelope


def test_request_id_generated_and_echoed():
    resp = APIClient().get("/api/v1/health/live/")
    assert len(resp["X-Request-ID"]) == 32


def test_malicious_inbound_request_id_is_replaced():
    resp = APIClient().get("/api/v1/health/live/", HTTP_X_REQUEST_ID="bad\nid<script>")
    assert resp["X-Request-ID"] != "bad\nid<script>" and len(resp["X-Request-ID"]) == 32


def test_error_envelope_shape(world):
    resp = world.client(world.engineer_a).get("/api/v1/customers/not-a-uuid/")
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == resp["X-Request-ID"]


def test_validation_error_envelope(world):
    resp = world.client(world.super_admin).post("/api/v1/customers/", {"code": ""})
    err = resp.json()["error"]
    assert resp.status_code == 400 and err["code"] == "validation_error" and "code" in err["details"]


def test_unhandled_exception_is_sanitised():
    class Boom(Exception):
        pass

    resp = api_exception_handler(Boom("SELECT * FROM secret_table WHERE password='x'"), {"view": None})
    assert resp.status_code == 500
    assert resp.data["error"]["code"] == "server_error"
    assert "secret_table" not in json.dumps(resp.data)


def test_non_api_404_is_json():
    resp = APIClient().get("/not-a-route/")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "not_found"


def test_security_headers_present():
    resp = APIClient().get("/api/v1/health/live/")
    assert resp["X-Content-Type-Options"] == "nosniff"
    assert resp["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp["Content-Security-Policy"]
    assert resp["Cache-Control"] == "no-store"


def test_403_is_audited_by_exception_handler(world):
    world.client(world.engineer_a).get("/api/v1/users/")
    assert AuditEvent.objects.filter(action="authz.denied", actor=world.engineer_a, target_id="/api/v1/users/").exists()


def test_permission_denied_message_generic():
    resp = api_exception_handler(exceptions.PermissionDenied(), {})
    assert resp.data["error"]["code"] == "permission_denied"


def test_health_ready_checks_database():
    resp = APIClient().get("/api/v1/health/ready/")
    assert resp.status_code == 200 and resp.json()["checks"]["database"] == "ok"
