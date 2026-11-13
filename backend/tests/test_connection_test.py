"""VSA1-01 administrator connection test via the documented GET /api/v3/ratelimits. Fixture-based only."""

from __future__ import annotations

import json

import pytest

from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationInstance
from apps.integrations.vsa.adapter import ALLOWED_PATHS
from apps.integrations.vsa.fixtures import DOC_RATE_LIMITS, FakeResponse, FixtureVsaTransport
from apps.integrations.vsa.schema import RecordInvalid, normalize_rate_limits

pytestmark = pytest.mark.django_db


def test_documented_rate_limit_example():
    out = normalize_rate_limits(DOC_RATE_LIMITS)
    assert out["failed_request_limits"][0] == {
        "limit": 100,
        "remaining": 100,
        "period_seconds": 60,
        "reset_seconds": None,
        "retry_seconds": None,
    }
    assets = next(e for e in out["endpoint_limits"] if e["endpoint"] == "Get Device Assets")
    assert assets["rules"][0]["retry_seconds"] == 122
    with pytest.raises(RecordInvalid):
        normalize_rate_limits({"Data": {"FailedRequestRateLimits": [{"Limit": "100", "PeriodInSeconds": 60}]}})
    with pytest.raises(RecordInvalid):
        normalize_rate_limits({"Data": []})


def test_route_is_exact():
    assert any(p.fullmatch("/api/v3/ratelimits") for p in ALLOWED_PATHS)
    assert not any(p.fullmatch("/api/v3/ratelimits/reset") for p in ALLOWED_PATHS)


@pytest.fixture
def inst(db):
    return IntegrationInstance.objects.create(
        name="VSA demo",
        provider="vsa_x",
        base_url="https://vsa.invalid",
        is_fixture=True,
        enabled=True,
        max_rps=20,
        credential_ref="env:SHOULD_NOT_APPEAR",
    )


def test_connection_test_ok_is_recorded_and_audited(world, inst):
    resp = world.client(world.super_admin).post(f"/api/v1/integrations/{inst.id}/test-connection/")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["outcome"] == "ok" and body["data_basis"] == "fixture" and body["latency_ms"] >= 0
    assert {e["endpoint"] for e in body["endpoint_limits"]} >= {"Get Device Assets", "Get Devices"}
    inst.refresh_from_db()
    assert inst.last_test_outcome == "ok" and inst.last_test_at is not None
    assert "SHOULD_NOT_APPEAR" not in json.dumps(inst.last_test_result)
    ev = AuditEvent.objects.get(action="integration.connection_test")
    assert ev.outcome == "success" and "SHOULD_NOT_APPEAR" not in json.dumps(ev.metadata)
    listed = world.client(world.super_admin).get("/api/v1/integrations/").json()["results"][0]
    assert listed["last_test_outcome"] == "ok"


def test_auth_failure_is_explicit_and_not_retried(world, inst, monkeypatch):
    calls = []

    def fake_get(self, url, **kw):
        calls.append(url)
        return FakeResponse(401)

    monkeypatch.setattr(FixtureVsaTransport, "get", fake_get)
    body = world.client(world.super_admin).post(f"/api/v1/integrations/{inst.id}/test-connection/").json()
    assert body["outcome"] == "auth_failed" and body["http_status"] == 401
    assert "not retried" in body["message"]
    assert len(calls) == 1
    assert AuditEvent.objects.get(action="integration.connection_test").outcome == "failure"


def test_undocumented_body_is_bad_response(world, inst, monkeypatch):
    monkeypatch.setattr(FixtureVsaTransport, "get", lambda self, url, **kw: FakeResponse(200, {"Data": "nope"}))
    body = world.client(world.super_admin).post(f"/api/v1/integrations/{inst.id}/test-connection/").json()
    assert body["outcome"] == "bad_response"


def test_only_system_admins_may_test(world, inst):
    for user in (world.admin_a, world.engineer_a, world.viewer_a):
        assert world.client(user).post(f"/api/v1/integrations/{inst.id}/test-connection/").status_code in (403, 404)
    assert world.client(None).post(f"/api/v1/integrations/{inst.id}/test-connection/").status_code in (401, 403)
