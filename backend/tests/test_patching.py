"""P2-01/P2-02 OS update collection and views (TESTING.md OS-01/OS-02). Fixture-based — not live validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.customers.models import CustomerSourceMapping
from apps.integrations import sync
from apps.integrations.models import DatasetGeneration, IntegrationInstance
from apps.integrations.vsa.adapter import ASSET_INCLUDE, VsaXAdapter
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.integrations.vsa.schema import RecordInvalid, normalize_asset, normalize_installed_updates
from apps.inventory.models import Asset
from apps.patching.models import DeviceOsUpdate, OsUpdate, PatchObservation

FIX = Path(__file__).parent / "fixtures" / "vsa_x"
LIST_DOC = json.loads((FIX / "assets_doc_example.json").read_text(encoding="utf-8"))
DETAIL_DOC = json.loads((FIX / "asset_detail_installed_updates_doc_example.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.django_db


def upd(kb: str, sev: str, uid: str | None = None) -> dict:
    return {
        "UpdateId": uid or f"u-{kb}",
        "RevisionNumber": 1,
        "KbArticle": kb,
        "Severity": sev,
        "Title": f"Update KB{kb}",
        "Category": "SECURITY_UPDATE",
        "CvssScore": 7.5,
        "CveCodes": ["CVE-0000-0001"],
        "ReleaseDate": "2026-10-14",
    }


def device(i: int, *, type_: str = "windows", available=None, installed=None, counts=True) -> dict:
    d = {
        "Identifier": f"d-{i:03d}",
        "Name": f"PC{i}",
        "OrganizationId": 11,
        "Type": type_,
        "LastSeenOnline": "2026-11-11T08:00:00Z",
        "InstalledSoftware": [],
    }
    if available is not None:
        d["AvailableUpdates"] = available
        if counts:
            d["Updates"] = {
                "Critical": sum(u["Severity"] == "Critical" for u in available),
                "Important": 0,
                "Unspecified": 0,
            }
    if installed is not None:
        d["InstalledUpdates"] = installed
    return d


@pytest.fixture
def vsa(world):
    inst = IntegrationInstance.objects.create(
        name="VSA", provider="vsa_x", base_url="https://vsa.invalid", is_fixture=True, enabled=True, max_rps=20
    )
    mapping = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="11",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    return inst, mapping


def run(mapping, user, transport):
    r, _ = sync.request_sync(mapping, requested_by=user)
    return sync.execute(str(r.id), adapter_factory=lambda i: VsaXAdapter(i, transport=transport, sleeper=lambda s: 0))


# ---------------------------------------------------------------- normalisation of documented examples


def test_documented_available_updates_and_counts():
    a = normalize_asset(LIST_DOC["Data"][0])
    assert a.update_counts == {"Critical": 0, "Important": 1, "Unspecified": 0}
    (u,) = a.available_updates
    assert (u.update_id, u.revision_number, u.kb_article, u.severity, u.cvss_score, u.release_date) == (
        "576b0dd6-57cc-457b-a5ec-e888491b395d",
        200,
        "5034441",
        "Important",
        7.0,
        "2024-01-09",
    )


def test_documented_installed_updates_keeps_timestamp_raw():
    (u,) = normalize_installed_updates(DETAIL_DOC, "11111111-2222-3333-4444-555555555555")
    assert u.installed_at_raw == "2024-01-07T00:00:00"  # no timezone in source: never converted
    assert u.installed_by_agent is True and u.kb_article == ""


def test_detail_identifier_mismatch_rejected():
    with pytest.raises(RecordInvalid):
        normalize_installed_updates(DETAIL_DOC, "someone-else")


@pytest.mark.parametrize(
    "bad",
    [
        {"AvailableUpdates": "x"},
        {"AvailableUpdates": [{"Title": "no id"}]},
        {"Updates": {"Critical": -1}},
        {"Updates": {"Critical": "1"}},
        {"Updates": []},
    ],
)
def test_malformed_update_sections_rejected(bad):
    item = {"Identifier": "x", "OrganizationId": 1, **bad}
    with pytest.raises(RecordInvalid):
        normalize_asset(item)


def test_out_of_range_values_dropped_not_trusted():
    item = {
        "Identifier": "x",
        "OrganizationId": 1,
        "AvailableUpdates": [{"UpdateId": "u", "KbArticle": "not-a-kb", "CvssScore": 99, "ReleaseDate": "Jan 2024"}],
    }
    (u,) = normalize_asset(item).available_updates
    assert (u.kb_article, u.cvss_score, u.release_date) == ("", None, "")


def test_list_include_requests_update_sections_only_from_documented_endpoint():
    assert "Updates" in ASSET_INCLUDE and "AvailableUpdates" in ASSET_INCLUDE
    assert "InstalledUpdates" not in ASSET_INCLUDE  # documented only on GET /api/v3/assets/:id


# ---------------------------------------------------------------- collection states (OS-01 / OS-02)


def test_states_never_produce_false_zeros(world, vsa):
    _, mapping = vsa
    data = [
        device(1, available=[upd("5099001", "Critical"), upd("5099002", "Important")]),
        device(2, available=[]),  # collected, genuinely zero
        device(3),  # Windows, section absent → not_collected
        device(4, type_="mac"),  # non-Windows → not_supported
    ]
    r = run(mapping, world.engineer_a, FixtureVsaTransport(data))
    assert r.state == "completed", r.error_code
    po = {p.asset.external_id: p for p in PatchObservation.objects.select_related("asset")}
    assert (po["d-001"].available_status, po["d-001"].available_count) == ("collected", 2)
    assert (po["d-002"].available_status, po["d-002"].available_count) == ("collected", 0)
    assert (po["d-003"].available_status, po["d-003"].available_count) == ("not_collected", None)
    assert (po["d-004"].available_status, po["d-004"].installed_status) == ("not_supported", "not_supported")

    s = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/os-updates/summary/").json()
    assert s["devices_total"] == 4 and s["devices_reporting_updates"] == 2
    assert s["devices_with_zero_available"] == 1  # only the device that actually reported an empty list
    assert s["devices_with_available_updates"] == 1
    assert s["available_section"]["not_collected"] == 1 and s["available_section"]["not_supported"] == 1
    assert s["devices_by_severity"]["Critical"] == 1
    assert {u["kb_article"] for u in s["top_available_updates"]} == {"5099001", "5099002"}
    assert "does not document a per-device update-scan timestamp" in s["freshness_note"]


def test_installed_updates_disabled_by_default_makes_no_detail_calls(world, vsa):
    _, mapping = vsa
    transport = FixtureVsaTransport([device(1, available=[], installed=[upd("1", "Unspecified")])])
    run(mapping, world.engineer_a, transport)
    assert not any(path.startswith("/api/v3/assets/") for path, _ in transport.calls)  # no per-device detail calls
    assert PatchObservation.objects.get().installed_status == "not_requested"


def test_installed_updates_budget_rotation_and_carry_forward(world, vsa):
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=2)
    data = [device(i, available=[], installed=[upd(f"50{i:05d}", "Unspecified", f"inst-{i}")]) for i in range(1, 5)]
    t1 = FixtureVsaTransport(data)
    r1 = run(mapping, world.engineer_a, t1)
    detail_calls = [p for p, _ in t1.calls if p.startswith("/api/v3/assets/")]
    assert len(detail_calls) == 2 and r1.installed_updates_requested == 2
    statuses = dict(
        PatchObservation.objects.filter(generation=r1.generation).values_list("asset__external_id", "installed_status")
    )
    assert sorted(statuses.values()) == ["collected", "collected", "not_requested", "not_requested"]

    t2 = FixtureVsaTransport(data)
    r2 = run(mapping, world.engineer_a, t2)
    second = {p.split("/")[-1] for p, _ in t2.calls if p.startswith("/api/v3/assets/")}
    first = {p.split("/")[-1] for p in detail_calls}
    assert second.isdisjoint(first)  # rotation: least recently collected devices first
    gen2 = PatchObservation.objects.filter(generation=r2.generation)
    assert sorted(gen2.values_list("installed_status", flat=True)) == [
        "carried_forward",
        "carried_forward",
        "collected",
        "collected",
    ]
    carried = gen2.filter(installed_status="carried_forward").first()
    assert carried.installed_collected_at is not None and carried.installed_count == 1
    assert DeviceOsUpdate.objects.filter(patch_observation=carried, state="installed").count() == 1


def test_detail_404_marks_only_that_device_failed(world, vsa):
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=5)
    data = [device(1, available=[], installed=[]), device(2, available=[], installed=[])]
    transport = FixtureVsaTransport(data)
    original_get = transport.get

    def get(url, **kw):
        if url.endswith("/api/v3/assets/d-001"):
            return FakeResponse(404)
        return original_get(url, **kw)

    transport.get = get  # type: ignore[method-assign]
    r = run(mapping, world.engineer_a, transport)
    assert r.state == "completed"
    st = dict(PatchObservation.objects.values_list("asset__external_id", "installed_status"))
    assert st == {"d-001": "failed", "d-002": "collected"}


def test_detail_auth_failure_fails_run_and_keeps_last_good(world, vsa):
    inst, mapping = vsa
    run(mapping, world.engineer_a, FixtureVsaTransport([device(1, available=[])]))
    good = DatasetGeneration.objects.get(is_current=True)
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=5)
    transport = FixtureVsaTransport([device(1, available=[], installed=[])])
    original_get = transport.get
    transport.get = lambda url, **kw: FakeResponse(401) if "/assets/d-" in url else original_get(url, **kw)  # type: ignore[method-assign]
    r = run(mapping, world.engineer_a, transport)
    assert r.state == "failed" and r.error_code == "auth_failed"
    assert DatasetGeneration.objects.get(is_current=True) == good


def test_unsafe_identifier_never_reaches_url(world, vsa):
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=5)
    bad = device(1, available=[])
    bad["Identifier"] = "../../automation/workflows/1/run"
    transport = FixtureVsaTransport([bad])
    r = run(mapping, world.engineer_a, transport)
    assert r.state == "completed"
    assert all("automation" not in p for p, _ in transport.calls)
    assert PatchObservation.objects.get().installed_status == "failed"


def test_os_update_identity_is_shared_but_rows_are_customer_scoped(world, vsa):
    inst, mapping = vsa
    run(mapping, world.engineer_a, FixtureVsaTransport([device(1, available=[upd("5099001", "Critical")])]))
    mb = CustomerSourceMapping.objects.create(
        customer=world.customer_b,
        integration_instance=inst,
        external_org_id="22",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    b = device(9, available=[upd("5099001", "Critical")])
    b["OrganizationId"] = 22
    run(mb, world.engineer_b, FixtureVsaTransport([b]))
    assert OsUpdate.objects.count() == 1 and DeviceOsUpdate.objects.count() == 2
    c = world.client(world.engineer_a)
    rows = c.get(f"/api/v1/customers/{world.customer_a.id}/os-updates/").json()
    assert rows["count"] == 1 and rows["results"][0]["hostname"] == "PC1"
    assert c.get(f"/api/v1/customers/{world.customer_b.id}/os-updates/").status_code == 404
    assert c.get(f"/api/v1/customers/{world.customer_b.id}/os-updates/summary/").status_code == 404
    assert c.get(f"/api/v1/customers/{world.customer_b.id}/os-updates/devices/").status_code == 404


def test_filters_and_device_status_list(world, vsa):
    _, mapping = vsa
    run(
        mapping,
        world.engineer_a,
        FixtureVsaTransport(
            [device(1, available=[upd("5099001", "Critical"), upd("5099002", "Important")]), device(2)]
        ),
    )
    c = world.client(world.viewer_a)
    base = f"/api/v1/customers/{world.customer_a.id}/os-updates/"
    assert c.get(base, {"kb": "KB5099001"}).json()["count"] == 1
    assert c.get(base, {"severity": "important"}).json()["count"] == 1
    assert c.get(base, {"kb": "'; DROP"}).json()["count"] == 0
    assert c.get(base, {"asset": "not-a-uuid"}).json()["count"] == 0
    devices = c.get(base + "devices/", {"available_status": "not_collected"}).json()
    assert devices["count"] == 1 and devices["results"][0]["hostname"] == "PC2"


def test_asset_detail_includes_os_updates(world, vsa):
    _, mapping = vsa
    run(mapping, world.engineer_a, FixtureVsaTransport([device(1, available=[upd("5099001", "Critical")])]))
    asset = Asset.objects.get()
    data = world.client(world.engineer_a).get(f"/api/v1/assets/{asset.id}/").json()
    assert data["os_updates"]["status"]["available_status"] == "collected"
    assert data["os_updates"]["updates"][0]["kb_article"] == "5099001"


def test_db_rejects_patch_rows_with_mismatched_customer(world, vsa):
    _, mapping = vsa
    run(mapping, world.engineer_a, FixtureVsaTransport([device(1, available=[upd("5099001", "Critical")])]))
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        DeviceOsUpdate.objects.update(customer=world.customer_b)


def test_demo_tenant_os_updates(world, vsa):
    inst, mapping = vsa
    CustomerSourceMapping.objects.filter(pk=mapping.pk).update(external_org_id="1001")
    mapping.refresh_from_db()
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=60)
    r, _ = sync.request_sync(mapping, requested_by=world.engineer_a)
    r = sync.execute(str(r.id))
    assert r.state == "completed", r.error_code
    s = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/os-updates/summary/").json()
    assert s["devices_total"] == 130
    assert s["available_section"]["not_supported"] > 0 and s["available_section"]["not_collected"] > 0
    # 60 budgeted detail calls: each device either returned InstalledUpdates or (by design) omitted the section.
    assert s["installed_section"]["collected"] + s["installed_section"]["not_collected"] == 60
    assert r.installed_updates_requested == 60
    assert sum(s["available_section"].values()) == 130
