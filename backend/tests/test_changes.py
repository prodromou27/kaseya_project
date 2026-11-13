"""VSA4-04 snapshot diff (R16) and VSA1-05 device reconciliation tab. Fixture-based only — NOT live validation."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.integrations.models import DatasetGeneration
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.inventory.models import Asset

from .test_onboarding import MAP, upload
from .test_p2_reporting import csv_rows
from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db


def first() -> list[dict]:
    a = [asset(i, 11, ip=f"10.0.1.{i}") for i in range(1, 5)]
    a[0]["InstalledSoftware"] = [{"Name": "7-Zip", "Publisher": "Igor Pavlov", "Version": "23.01"}]
    a[1]["ClientVersion"] = "5.0.7"
    return a


def second() -> list[dict]:
    a = [asset(i, 11, ip=f"10.0.1.{i}") for i in (1, 2, 3, 5)]  # PC4 gone, PC5 new
    a[0]["Name"] = "PC1-RENAMED"
    a[0]["InstalledSoftware"] = [{"Name": "7-Zip", "Publisher": "Igor Pavlov", "Version": "24.08"}]
    a[1]["_GroupId"], a[1]["ClientVersion"] = 52, "5.1.2"
    a[2]["LocalIpAddresses"][0]["IpV4"] = "10.0.1.99"
    return a


@pytest.fixture
def two(world, env):  # noqa: F811
    run(env["ma"], world.engineer_a, FixtureVsaTransport(first()))
    run(env["ma"], world.engineer_a, FixtureVsaTransport(second()))
    run(env["mb"], world.engineer_b, FixtureVsaTransport([asset(1, 22, ip="10.0.1.10", site=8, group=81)]))
    return env


def url(c, tail):
    return f"/api/v1/customers/{c.id}/{tail}"


def test_diff_current_vs_previous(world, two):
    c = world.client(world.viewer_a)
    s = c.get(url(world.customer_a, "changes/")).json()
    assert s["counts"]["device_added"] == 1 and s["counts"]["device_removed"] == 1
    assert s["counts"]["hostname"] == 1 and s["counts"]["group"] == 1 and s["counts"]["agent_version"] == 1
    assert s["counts"]["ip_addresses"] == 1 and s["counts"]["software"] == 1
    assert s["devices_compared"] == 3 and s["from"]["devices"] == 4 and s["to"]["devices"] == 4
    assert "no person is attributed" in s["note"]
    rows = c.get(url(world.customer_a, "changes/devices/?kind=software")).json()["results"]
    sw = rows[0]["changes"][-1]
    assert rows[0]["hostname"] == "PC1-RENAMED" and sw["added"] == ["7-Zip 24.08"] and sw["removed"] == ["7-Zip 23.01"]
    ip = c.get(url(world.customer_a, "changes/devices/?kind=ip_addresses")).json()["results"][0]["changes"]
    assert ip == [{"kind": "ip_addresses", "added": ["10.0.1.99"], "removed": ["10.0.1.3"]}]


def test_sections_absent_in_either_snapshot_are_not_compared(world, env):  # noqa: F811
    a = first()
    a[2].pop("LocalIpAddresses")
    run(env["ma"], world.engineer_a, FixtureVsaTransport(a))
    run(env["ma"], world.engineer_a, FixtureVsaTransport(second()))
    s = world.client(world.viewer_a).get(url(world.customer_a, "changes/")).json()
    assert s["counts"]["ip_addresses"] == 0  # PC3's change cannot be claimed
    assert s["not_compared"]["ip_addresses"] == 1


def test_pairs_are_validated_and_customer_scoped(world, two):
    c = world.client(world.viewer_a)
    snaps = c.get(url(world.customer_a, "changes/snapshots/")).json()
    assert len(snaps) == 2 and snaps[0]["is_current"]
    old, new = snaps[1]["id"], snaps[0]["id"]
    reversed_ = c.get(url(world.customer_a, f"changes/?from={new}&to={old}")).json()
    assert reversed_["from"]["id"] == old  # always older -> newer
    assert c.get(url(world.customer_a, f"changes/?from={new}&to={new}")).status_code == 400
    gen_b = DatasetGeneration.objects.get(customer=world.customer_b, is_current=True)
    assert c.get(url(world.customer_a, f"changes/?from={gen_b.id}")).status_code == 400
    assert world.client(world.engineer_b).get(url(world.customer_a, "changes/")).status_code == 404
    resp = world.client(world.engineer_b).get(url(world.customer_b, "changes/"))
    assert resp.status_code == 400 and "no earlier complete snapshot" in resp.json()["error"]["details"]["detail"]


def test_r16_report(world, two, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.engineer_a).post(
            url(world.customer_a, "reports/"),
            {"report_type": "inventory_changes", "format": "csv", "filters": {}},
            format="json",
        )
    assert resp.status_code == 202, resp.content
    raw = world.client(world.engineer_a).get(f"/api/v1/reports/{resp.json()['id']}/download/")
    provenance, rows = csv_rows(b"".join(raw.streaming_content))
    assert any("no person is attributed" in p for p in provenance)
    assert sorted({r[3] for r in rows}) == [
        "agent_version",
        "device_added",
        "device_removed",
        "group",
        "hostname",
        "ip_addresses",
        "software",
    ]


def test_asset_detail_reconciliation_tab(world, env, django_capture_on_commit_callbacks):  # noqa: F811
    run(env["ma"], world.engineer_a, FixtureVsaTransport(first()))
    DatasetGeneration.objects.filter(customer=world.customer_a, is_current=True).update(published_at=timezone.now())
    eng = world.client(world.engineer_a)
    up = upload(
        eng, world.customer_a, [["Hostname", "Serial", "Site", "Group", "Notes"], ["PC2", "", "5", "G99", ""]]
    ).json()
    with django_capture_on_commit_callbacks(execute=True):
        r = eng.post(
            url(world.customer_a, "onboarding/runs/"),
            {"upload": up["id"], "sheet": "CSV", "mapping": MAP},
            format="json",
        )
    assert r.status_code == 202, r.content
    pc2 = Asset.objects.get(customer=world.customer_a, external_id="11-dev-002")
    recon = world.client(world.viewer_a).get(f"/api/v1/assets/{pc2.id}/").json()["reconciliation"]
    assert recon[0]["role"] == "matched" and recon[0]["classification"] == "MATCHED_WRONG_GROUP"
    pc3 = Asset.objects.get(customer=world.customer_a, external_id="11-dev-003")
    recon3 = world.client(world.viewer_a).get(f"/api/v1/assets/{pc3.id}/").json()["reconciliation"]
    assert recon3[0]["kind"] == "unexpected"
