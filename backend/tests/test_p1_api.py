"""P1-04/05/06/08/09 API tests: tenant isolation, catalog workflow, compliance metrics, scoped CSV."""

from __future__ import annotations

import csv
import io
from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.customers.models import CustomerSourceMapping
from apps.integrations import sync
from apps.integrations.models import IntegrationInstance, SyncQuarantine
from apps.integrations.vsa.adapter import VsaXAdapter
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.inventory.models import Asset
from apps.software.models import CatalogRevision, ComplianceEvaluation, ComplianceResult, SoftwareInstallation

from .factories import UserFactory, role

pytestmark = pytest.mark.django_db

NOW = timezone.now()


def vsa_assets(n: int, org: int, prefix: str, chrome: str = "130.0.1.1") -> list[dict]:
    return [
        {
            "Identifier": f"{prefix}-{i:03d}",
            "Name": f"{prefix.upper()}-PC{i}",
            "OrganizationId": org,
            "SiteId": 1,
            "GroupName": f"{prefix} - HQ - WS",
            "LastSeenOnline": "2026-11-11T08:00:00Z",
            "Type": "windows",
            "AssetInfo": [{"CategoryName": "Operating System", "CategoryData": {"Name": "Windows 11 Enterprise"}}],
            "InstalledSoftware": [
                {"Name": "Google Chrome", "Publisher": "Google LLC", "Version": chrome if i % 2 else "131.0.6778.86"},
                {"Name": "Contoso Tool", "Publisher": "Contoso", "Version": "1.0"},
            ],
        }
        for i in range(n)
    ]


def do_sync(mapping, user, data):
    run, _ = sync.request_sync(mapping, requested_by=user)
    transport = FixtureVsaTransport(data)
    return sync.execute(str(run.id), adapter_factory=lambda i: VsaXAdapter(i, transport=transport, sleeper=lambda s: 0))


@pytest.fixture
def synced(world, django_capture_on_commit_callbacks):
    inst = IntegrationInstance.objects.create(
        name="VSA", provider="vsa_x", base_url="https://vsa.invalid", is_fixture=True, enabled=True, max_rps=20
    )
    ma = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="11",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=NOW,
    )
    mb = CustomerSourceMapping.objects.create(
        customer=world.customer_b,
        integration_instance=inst,
        external_org_id="22",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=NOW,
    )
    a_data = vsa_assets(6, 11, "a")
    a_data[0]["Name"] = '=HYPERLINK("http://evil.invalid")'  # hostile vendor text
    assert do_sync(ma, world.engineer_a, a_data).state == "completed"
    assert do_sync(mb, world.engineer_b, vsa_assets(4, 22, "b")).state == "completed"
    return {"instance": inst, "mapping_a": ma, "mapping_b": mb}


@pytest.fixture
def reviewer(db):
    return UserFactory(email="reviewer@example.test", global_role=role("super_admin"))


def chrome_import(client, version="131.0.6778.86", name="Google Chrome"):
    row = {
        "vendor": "Google",
        "product": "Chrome",
        "channel": "stable",
        "reference_version": version,
        "vendor_url": "https://chromereleases.googleblog.com/",
        "source_type": "vendor_release_notes",
        "source_checked_at": (NOW - timedelta(hours=1)).isoformat(),
        "aliases": [{"name_pattern": name, "publisher_pattern": "Google LLC", "match_type": "exact"}],
    }
    return client.post("/api/v1/catalog/imports/", {"rows": [row]})


def approve_chrome(world, reviewer, capture, version="131.0.6778.86"):
    resp = chrome_import(world.client(world.super_admin), version)
    assert resp.status_code == 201, resp.content
    with capture(execute=True):
        resp = world.client(reviewer).post(f"/api/v1/catalog/imports/{resp.json()['id']}/approve/")
    assert resp.status_code == 200, resp.content
    return resp


# ---------------------------------------------------------------- assets (P1-04)


def test_assets_are_customer_scoped(world, synced):
    a = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/assets/").json()
    assert a["count"] == 6 and all(r["external_id"].startswith("a-") for r in a["results"])
    assert a["results"][0]["data_basis"] == "fixture" and a["results"][0]["as_of"]
    assert world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_b.id}/assets/").status_code == 404
    b_asset = Asset.objects.filter(customer=world.customer_b).first()
    assert world.client(world.engineer_a).get(f"/api/v1/assets/{b_asset.id}/").status_code == 404
    assert world.client(world.engineer_b).get(f"/api/v1/assets/{b_asset.id}/").status_code == 200


def test_asset_search_filter_order_and_validation(world, synced):
    c = world.client(world.viewer_a)
    base = f"/api/v1/customers/{world.customer_a.id}/assets/"
    assert c.get(base, {"search": "A-PC3"}).json()["count"] == 1
    assert c.get(base, {"search": "b-000"}).json()["count"] == 0  # B's ID via search: nothing
    assert c.get(base, {"os": "Windows 11 Enterprise"}).json()["count"] == 6
    names = [r["hostname"] for r in c.get(base, {"ordering": "-hostname"}).json()["results"]]
    assert names == sorted(names, reverse=True)
    assert c.get(base, {"ordering": "password"}).status_code == 400
    assert c.get(base, {"offline": "true", "offline_days": "abc"}).status_code == 400
    facets = c.get(base + "facets/").json()
    assert facets["os"] == ["Windows 11 Enterprise"] and facets["group"] == ["a - HQ - WS"]


def test_asset_detail_includes_history_and_classified_software(world, synced):
    asset = Asset.objects.filter(customer=world.customer_a).first()
    data = world.client(world.engineer_a).get(f"/api/v1/assets/{asset.id}/").json()
    assert data["in_current_dataset"] and len(data["history"]) == 1
    assert {s["state"] for s in data["software"]} == {"unsupported"}


def test_revoked_mapping_hides_published_data(world, synced):
    CustomerSourceMapping.objects.filter(pk=synced["mapping_a"].pk).update(mapping_status="revoked")
    c = world.client(world.engineer_a)
    assert c.get(f"/api/v1/customers/{world.customer_a.id}/assets/").json()["count"] == 0
    assert c.get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()["eligible_installations"] == 0


def test_dataset_freshness_and_staleness(world, synced, settings):
    c = world.client(world.viewer_a)
    data = c.get(f"/api/v1/customers/{world.customer_a.id}/datasets/").json()
    assert data[0]["status"] == "fresh" and data[0]["row_count"] == 6 and data[0]["last_run"]["state"] == "completed"
    settings.DATA_STALE_AFTER_HOURS = 0
    assert c.get(f"/api/v1/customers/{world.customer_a.id}/datasets/").json()[0]["status"] == "stale"


def test_sync_run_endpoint_permissions(world, synced, django_capture_on_commit_callbacks):
    url = f"/api/v1/customers/{world.customer_a.id}/sync-runs/"
    assert world.client(world.viewer_a).post(url).status_code == 404  # no customer.sync
    assert world.client(world.viewer_a).get(url).status_code == 200
    assert world.client(world.engineer_b).post(url).status_code == 404
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.engineer_a).post(url)
    assert resp.status_code == 202 and len(resp.json()["runs"]) == 1


def test_quarantine_and_discovery_are_super_admin_only(world, synced):
    for user in (world.admin_a, world.engineer_a):
        assert world.client(user).get("/api/v1/sync-quarantine/").status_code == 403
        assert world.client(user).get(f"/api/v1/integrations/{synced['instance'].id}/organizations/").status_code == 403
    resp = world.client(world.super_admin).get(f"/api/v1/integrations/{synced['instance'].id}/organizations/")
    orgs = {o["external_org_id"]: o for o in resp.json()["organizations"]}
    assert resp.json()["data_basis"] == "fixture" and orgs["1999"]["mapping"] is None


def test_vsa_mapping_requires_integer_org_id(world, synced):
    resp = world.client(world.admin_a).post(
        f"/api/v1/customers/{world.customer_a.id}/mappings/",
        {"integration_instance": str(synced["instance"].id), "external_org_id": "7 or 1 eq 1"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------- catalog workflow (P1-06)


def test_catalog_import_preview_saves_nothing(world, synced):
    c = world.client(world.super_admin)
    row = {
        "vendor": "Google",
        "product": "Chrome",
        "reference_version": "131.0",
        "vendor_url": "https://x.invalid/",
        "source_type": "vendor_release_notes",
        "source_checked_at": NOW.isoformat(),
    }
    resp = c.post("/api/v1/catalog/imports/preview/", {"rows": [row, {**row, "reference_version": "latest"}]})
    assert resp.status_code == 200 and resp.json()["valid"] is False
    assert resp.json()["rows"][0]["change"] == "new_product"
    assert not CatalogRevision.objects.exists()


def test_catalog_requires_separate_reviewer(world, synced, reviewer, django_capture_on_commit_callbacks):
    imp = chrome_import(world.client(world.super_admin)).json()
    assert world.client(world.super_admin).post(f"/api/v1/catalog/imports/{imp['id']}/approve/").status_code == 400
    assert not CatalogRevision.objects.exists()
    approve_chrome_from(imp, reviewer, world, django_capture_on_commit_callbacks)
    rev = CatalogRevision.objects.get()
    assert rev.created_by == world.super_admin and rev.reviewed_by == reviewer
    assert AuditEvent.objects.filter(action="catalog.import_approved").exists()


def approve_chrome_from(imp, reviewer, world, capture):
    with capture(execute=True):
        resp = world.client(reviewer).post(f"/api/v1/catalog/imports/{imp['id']}/approve/")
    assert resp.status_code == 200, resp.content


def test_catalog_is_admin_only(world, synced):
    for user in (world.admin_a, world.engineer_a):
        assert world.client(user).get("/api/v1/catalog/products/").status_code == 403
        assert chrome_import(world.client(user)).status_code == 403


def test_approval_reclassifies_and_metrics_reconcile(world, synced, reviewer, django_capture_on_commit_callbacks):
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks)
    s = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()
    # 6 assets: odd indices run 130.x (outdated), even run the reference (current). Contoso is uncatalogued.
    assert s["totals"] == {"current": 3, "outdated": 3, "newer": 0, "unknown": 0, "unsupported": 6, "excluded": 0}
    assert s["eligible_installations"] == 12 == SoftwareInstallation.objects.filter(customer=world.customer_a).count()
    assert s["comparable_installations"] == 6 and s["comparable_coverage_pct"] == 50.0
    assert s["version_compliance_pct"] == 50.0 and s["unique_assets_with_outdated"] == 3
    chrome = s["products"][0]
    assert chrome["states"]["outdated"] == 3 and chrome["unique_assets"] == 6
    assert sum(v["installations"] for v in chrome["versions"]) == chrome["installations"]
    listed = (
        world.client(world.engineer_a)
        .get(f"/api/v1/customers/{world.customer_a.id}/software/", {"state": "outdated", "page_size": 200})
        .json()
    )
    assert listed["count"] == 3 and all(r["reference_version"] == "131.0.6778.86" for r in listed["results"])
    assert listed["results"][0]["catalog_source_url"].startswith("https://")
    assert "not evidence of missing third-party" in s["disclaimer"].lower()
    # B is evaluated independently and never mixed into A's numbers
    sb = world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_b.id}/software/summary/").json()
    assert sb["eligible_installations"] == 8


def test_software_endpoints_are_scoped(world, synced):
    for path in ("software/", "software/summary/", "software-exceptions/"):
        assert world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_b.id}/{path}").status_code == 404
    assert (
        world.client(world.engineer_a)
        .get(f"/api/v1/customers/{world.customer_a.id}/software/", {"asset": "not-a-uuid"})
        .json()["count"]
        == 0
    )


def test_published_revision_immutable_in_orm_and_db(world, synced, reviewer, django_capture_on_commit_callbacks):
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks)
    rev = CatalogRevision.objects.get()
    rev.reference_version = "999.0"
    with pytest.raises(ValueError, match="immutable"):
        rev.save()
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic(), connection.cursor() as cur:
        cur.execute("UPDATE software_catalogrevision SET reference_version = '1.0'")
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("DELETE FROM software_catalogrevision")


def test_new_revision_keeps_history_reproducible(world, synced, reviewer, django_capture_on_commit_callbacks):
    """SOFT-05: an older evaluation and its results are preserved after a new reference is approved."""
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks, "131.0.6778.86")
    old_eval = ComplianceEvaluation.objects.get(customer=world.customer_a, is_current=True)
    old_states = dict(ComplianceResult.objects.filter(evaluation=old_eval).values_list("id", "state"))
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks, "132.0.1.1")
    new_eval = ComplianceEvaluation.objects.get(customer=world.customer_a, is_current=True)
    assert new_eval.id != old_eval.id
    old_eval.refresh_from_db()
    assert dict(ComplianceResult.objects.filter(evaluation=old_eval).values_list("id", "state")) == old_states
    assert ComplianceResult.objects.filter(evaluation=new_eval, state="outdated").count() == 6


def test_version_down_is_flagged_in_preview(world, synced, reviewer, django_capture_on_commit_callbacks):
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks, "131.0.6778.86")
    row = {
        "vendor": "Google",
        "product": "Chrome",
        "reference_version": "100.0",
        "vendor_url": "https://x.invalid/",
        "source_type": "vendor_release_notes",
        "source_checked_at": NOW.isoformat(),
    }
    preview = world.client(world.super_admin).post("/api/v1/catalog/imports/preview/", {"rows": [row]}).json()
    assert preview["rows"][0]["change"] == "version_down" and preview["rows"][0]["warnings"]


def test_alias_review_flow(world, synced, reviewer, django_capture_on_commit_callbacks):
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks)
    product = CatalogRevision.objects.get().product
    resp = world.client(world.super_admin).post(
        "/api/v1/catalog/aliases/", {"product": str(product.id), "name_pattern": "Contoso Tool", "match_type": "exact"}
    )
    alias_id = resp.json()["id"]
    assert resp.json()["review_status"] == "proposed"
    assert world.client(world.super_admin).post(f"/api/v1/catalog/aliases/{alias_id}/approve/").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        assert world.client(reviewer).post(f"/api/v1/catalog/aliases/{alias_id}/approve/").status_code == 200
    s = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()
    assert s["totals"]["unsupported"] == 0  # Contoso now mapped (to the Chrome product, as the reviewer approved)


# ---------------------------------------------------------------- exceptions (SOFT-04)


def test_exceptions_scoped_and_raw_observation_unchanged(world, synced, reviewer, django_capture_on_commit_callbacks):
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks)
    product = CatalogRevision.objects.get().product
    url = f"/api/v1/customers/{world.customer_a.id}/software-exceptions/"
    body = {
        "product": str(product.id),
        "reason": "Pinned by vendor LOB app until Q1",
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
    }
    assert world.client(world.engineer_a).post(url, body).status_code == 404  # engineer lacks capability
    b_asset = Asset.objects.filter(customer=world.customer_b).first()
    assert world.client(world.admin_a).post(url, {**body, "asset": str(b_asset.id)}).status_code == 400
    assert (
        world.client(world.admin_a)
        .post(url, {**body, "expires_at": (NOW + timedelta(days=500)).isoformat()})
        .status_code
        == 400
    )
    raw_before = list(
        SoftwareInstallation.objects.filter(customer=world.customer_a).values_list("raw_version", flat=True)
    )
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.admin_a).post(url, body)
    assert resp.status_code == 201
    s = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()
    assert s["totals"]["excluded"] == 6 and s["totals"]["outdated"] == 0
    assert (
        list(SoftwareInstallation.objects.filter(customer=world.customer_a).values_list("raw_version", flat=True))
        == raw_before
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert world.client(world.admin_a).delete(f"{url}{resp.json()['id']}/").status_code == 204
    s = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()
    assert s["totals"]["outdated"] == 3


# ---------------------------------------------------------------- scoped CSV with provenance (P1-09)


def _csv(world, user, customer, report_type, capture, filters=None):
    client = world.client(user)
    with capture(execute=True):
        resp = client.post(
            f"/api/v1/customers/{customer.id}/reports/", {"report_type": report_type, "filters": filters or {}}
        )
    assert resp.status_code == 202, resp.content
    run_id = resp.json()["id"]
    dl = client.get(f"/api/v1/reports/{run_id}/download/")
    assert dl.status_code == 200
    return list(csv.reader(io.StringIO(b"".join(dl.streaming_content).decode("utf-8-sig")))), run_id


def test_asset_inventory_csv_scoped_with_provenance_and_injection_defence(
    world, synced, django_capture_on_commit_callbacks
):
    rows, _ = _csv(world, world.engineer_a, world.customer_a, "asset_inventory", django_capture_on_commit_callbacks)
    provenance = [r[0] for r in rows if r and r[0].startswith("# ")]
    assert any(p.startswith("# Datasets: VSA assets generation") for p in provenance)
    assert "# Data basis: fixture" in provenance and "# Records included: 6" in provenance
    header = rows.index(next(r for r in rows if r and r[0] == "device_id"))
    data = rows[header + 1 :]
    assert len(data) == 6 and all(r[0].startswith("a-") for r in data)
    assert any(r[1] == '\'=HYPERLINK("http://evil.invalid")' for r in data)
    api_count = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/assets/").json()["count"]
    assert api_count == len(data)  # REP-01: UI/API list and export are the same record set


def test_software_csv_matches_api_and_states_limitations(world, synced, reviewer, django_capture_on_commit_callbacks):
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks)
    rows, _ = _csv(
        world,
        world.engineer_a,
        world.customer_a,
        "software_compliance",
        django_capture_on_commit_callbacks,
        {"state": "outdated"},
    )
    assert any("NOT evidence of missing third-party patches" in r[0] for r in rows if r)
    assert any(r[0].startswith("# Applied catalog revision: 1 revision(s)") for r in rows if r)
    header = rows.index(next(r for r in rows if r and r[0] == "device_id"))
    data = rows[header + 1 :]
    api = (
        world.client(world.engineer_a)
        .get(f"/api/v1/customers/{world.customer_a.id}/software/", {"state": "outdated"})
        .json()
    )
    assert len(data) == api["count"] == 3 and {r[8] for r in data} == {"outdated"}


def test_report_filters_cannot_reach_other_customer(world, synced, django_capture_on_commit_callbacks):
    rows, _ = _csv(
        world,
        world.engineer_a,
        world.customer_a,
        "asset_inventory",
        django_capture_on_commit_callbacks,
        {"search": "b-"},
    )
    header = rows.index(next(r for r in rows if r and r[0] == "device_id"))
    assert rows[header + 1 :] == []
    resp = world.client(world.engineer_a).post(
        f"/api/v1/customers/{world.customer_b.id}/reports/", {"report_type": "asset_inventory"}
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "filters",
    [
        {"search": "a-003"},
        {"search": "A-PC3"},
        {"site": "1", "device_type": "windows", "ordering": "-hostname"},
        {"group": "a - HQ - WS", "os": "Windows 11 Enterprise"},
        {"group_id": "does-not-exist"},
        {"organization": "22"},
        {"offline": True, "offline_days": 1},
        {"offline": False, "offline_days": 365},
    ],
)
def test_inventory_export_matches_filtered_api(world, synced, django_capture_on_commit_callbacks, filters):
    """CX-01: report and API use identical customer-scoped rows and ordering, including source-ID search."""
    response = world.client(world.engineer_a).get(
        f"/api/v1/customers/{world.customer_a.id}/assets/",
        {k: str(v).lower() if isinstance(v, bool) else v for k, v in filters.items()},
    )
    assert response.status_code == 200
    rows, _ = _csv(
        world, world.engineer_a, world.customer_a, "asset_inventory", django_capture_on_commit_callbacks, filters
    )
    header = rows.index(next(r for r in rows if r and r[0] == "device_id"))
    assert [r[0] for r in rows[header + 1 :]] == [r["external_id"] for r in response.json()["results"]]
    assert all(not r[0].startswith("b-") for r in rows[header + 1 :])


@pytest.mark.parametrize("filters", [{"offline_days": 0}, {"offline": "maybe"}, {"instance": "invalid"}])
def test_inventory_filters_invalid_in_api_and_report(world, synced, filters):
    client = world.client(world.engineer_a)
    base = f"/api/v1/customers/{world.customer_a.id}"
    assert client.get(f"{base}/assets/", filters).status_code == 400
    assert client.post(f"{base}/reports/", {"report_type": "asset_inventory", "filters": filters}).status_code == 400


def test_inventory_offline_report_pins_cutoff(world, synced, monkeypatch, django_capture_on_commit_callbacks):
    from apps.inventory.models import AssetObservation
    from apps.reporting.models import ReportRun
    from apps.reporting.registry import REPORT_TYPES

    AssetObservation.objects.filter(customer=world.customer_a).update(last_seen_online=NOW - timedelta(days=6))
    rows, _ = _csv(
        world,
        world.engineer_a,
        world.customer_a,
        "asset_inventory",
        django_capture_on_commit_callbacks,
        {"offline": True, "offline_days": 7},
    )
    original = ReportRun.objects.get(customer=world.customer_a, report_type="asset_inventory")
    pins = original.as_of_generation_ids
    assert pins["inventory_filter_at"]
    monkeypatch.setattr(timezone, "now", lambda: NOW + timedelta(days=20))
    report = REPORT_TYPES["asset_inventory"]
    re_pins = report.pin(world.customer_a, pins)
    assert list(report.rows(world.customer_a, original.filters, re_pins)) == []
    header = rows.index(next(r for r in rows if r and r[0] == "device_id"))
    assert rows[header + 1 :] == []


def test_selected_device_report_is_scoped_and_exact(world, synced, django_capture_on_commit_callbacks):
    selected = list(Asset.objects.filter(customer=world.customer_a).order_by("external_id")[:2])
    rows, _ = _csv(
        world,
        world.engineer_a,
        world.customer_a,
        "asset_inventory",
        django_capture_on_commit_callbacks,
        {"asset_ids": ",".join(str(asset.id) for asset in selected)},
    )
    header = rows.index(next(row for row in rows if row and row[0] == "device_id"))
    assert {row[0] for row in rows[header + 1 :]} == {asset.external_id for asset in selected}
    foreign = Asset.objects.filter(customer=world.customer_b).first()
    response = world.client(world.engineer_a).post(
        f"/api/v1/customers/{world.customer_a.id}/reports/",
        {"report_type": "asset_inventory", "filters": {"asset_ids": f"{selected[0].id},{foreign.id}"}},
    )
    assert response.status_code == 400
    response = world.client(world.engineer_a).post(
        f"/api/v1/customers/{world.customer_a.id}/reports/",
        {"report_type": "asset_inventory", "filters": {"asset_ids": "invalid"}},
    )
    assert response.status_code == 400


def test_quarantined_records_absent_from_customer_views(world, synced):
    data = vsa_assets(2, 11, "x") + vsa_assets(1, 99, "leak")
    transport = FixtureVsaTransport([], scripted=[FakeResponse(200, {"Data": data, "Meta": {"TotalCount": 3}})])
    run, _ = sync.request_sync(synced["mapping_a"], requested_by=world.engineer_a)
    SyncQuarantine.objects.all().delete()
    sync.execute(str(run.id), adapter_factory=lambda i: VsaXAdapter(i, transport=transport, sleeper=lambda s: 0))
    assets = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/assets/").json()
    assert all(not r["external_id"].startswith("leak") for r in assets["results"])
