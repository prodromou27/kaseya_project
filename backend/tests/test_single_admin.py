"""Default deployment has one administrator: they can approve their own changes, and every approval is audited."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db
URL = "/api/v1/catalog/lifecycle/"
ENTRY = {
    "kind": "os",
    "os_family": "Windows 11",
    "release_label": "23H2",
    "end_of_support": "2027-11-10",
    "source_url": "https://lifecycle-evidence.example.test/page",
    "source_type": "vendor_lifecycle_page",
    "source_checked_at": "2026-11-01",
    "confidence": "official",
}


def test_self_approval_allowed_when_second_approver_not_required(world, settings):
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    client = world.client(world.super_admin)
    eid = client.post(URL, ENTRY, format="json").json()["id"]
    resp = client.post(f"{URL}{eid}/approve/", {}, format="json")
    assert resp.status_code == 200 and resp.json()["reviewed_by"] == world.super_admin.email
    assert AuditEvent.objects.filter(action="lifecycle.approved", target_id=eid).exists()


def test_self_approval_refused_when_second_approver_required(world, settings):
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = True
    client = world.client(world.super_admin)
    eid = client.post(URL, ENTRY, format="json").json()["id"]
    assert client.post(f"{URL}{eid}/approve/", {}, format="json").status_code == 400


def test_setting_defaults_to_single_admin(monkeypatch):
    import importlib

    import config.settings as s

    monkeypatch.delenv("REQUIRE_SECOND_APPROVER", raising=False)
    monkeypatch.delenv("CATALOG_REQUIRE_SEPARATE_REVIEWER", raising=False)
    assert importlib.reload(s).CATALOG_REQUIRE_SEPARATE_REVIEWER is False
    monkeypatch.setenv("REQUIRE_SECOND_APPROVER", "true")
    assert importlib.reload(s).CATALOG_REQUIRE_SEPARATE_REVIEWER is True
    monkeypatch.delenv("REQUIRE_SECOND_APPROVER")
    importlib.reload(s)
