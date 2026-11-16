"""A non-JSON answer from VSA X: per-device detail calls skip that device; core calls fail the run and say where."""

from __future__ import annotations

import logging

import pytest

from apps.audit.models import AuditEvent
from apps.integrations.http import endpoint_template
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.patching.models import AppliedPolicyObservation

from .test_patch_policies import POLICIES, _assets, _set_budget
from .test_vsa1_hierarchy_network import env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db


def not_json(status=200):
    return FakeResponse(status, ValueError("Expecting value"), {"Content-Type": "text/html"})


def test_one_device_answering_with_non_json_does_not_fail_the_sync(world, env):  # noqa: F811
    _set_budget(env, 10)
    t = FixtureVsaTransport(_assets(), patch_policies=POLICIES)
    original = t.get
    t.get = lambda url, **kw: not_json() if url.endswith("11-dev-002/appliedpolicies") else original(url, **kw)  # type: ignore[method-assign]
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "completed", r.error_code
    o = AppliedPolicyObservation.objects.get(generation_id=r.generation_id, asset__external_id="11-dev-002")
    assert o.status == "failed"


def test_every_device_answering_non_json_marks_the_section_incomplete_not_the_sync(world, env):  # noqa: F811
    _set_budget(env, 10)
    t = FixtureVsaTransport(_assets(), patch_policies=POLICIES)
    original = t.get
    t.get = lambda url, **kw: not_json() if url.endswith("/appliedpolicies") else original(url, **kw)  # type: ignore[method-assign]
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "completed", r.error_code


def test_core_call_with_non_json_fails_and_names_the_endpoint(world, env, caplog):  # noqa: F811
    t = FixtureVsaTransport(_assets())
    original = t.get
    t.get = lambda url, **kw: not_json() if url.endswith("/api/v3/groups") else original(url, **kw)  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="portal.connectors"):
        r = run(env["ma"], world.engineer_a, t)
    assert (r.state, r.error_code) == ("failed", "bad_response")
    event = AuditEvent.objects.get(action="sync.failed", target_id=str(r.id))
    assert event.metadata == {"error_code": "bad_response", "endpoint": "/api/v3/groups"}
    record = next(x for x in caplog.records if x.getMessage() == "vendor_bad_response")
    assert (record.endpoint, record.status, record.content_type) == ("/api/v3/groups", 200, "text/html")

    from apps.core.system_status import collect

    status = collect(check_worker=False)
    text = " ".join(str(item) for item in status["findings"])
    assert "not JSON" in text and "Endpoint: /api/v3/groups." in text


def test_endpoint_template_hides_identifiers():
    assert endpoint_template("/api/v3/devices/7c1e-42ab/appliedpolicies") == "/api/v3/devices/:id/appliedpolicies"
    assert endpoint_template("/api/v3/patchmanagement/policies/301") == "/api/v3/patchmanagement/policies/:id"
    assert endpoint_template("/api/v3/assets") == "/api/v3/assets"
