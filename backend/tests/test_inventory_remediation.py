"""Source identity and network-search export regressions; synthetic PostgreSQL fixtures only."""

import csv
import io

import pytest
from django.utils import timezone

from apps.customers.models import CustomerSourceMapping
from apps.integrations.models import IntegrationInstance
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.inventory.models import ExpectedSubnet

from .test_vsa1_hierarchy_network import asset, env, run, synced  # noqa: F401 - shared fixtures

pytestmark = pytest.mark.django_db


def test_identical_group_ids_are_source_scoped(world, synced):  # noqa: F811
    second = IntegrationInstance.objects.create(
        name="Second VSA", provider="vsa_x", base_url="https://second.invalid", is_fixture=True, enabled=True
    )
    mapping = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=second,
        external_org_id="11",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    assert run(mapping, world.engineer_a, FixtureVsaTransport([asset(99, 11, group=51)])).state == "completed"
    client = world.client(world.engineer_a)
    base = f"/api/v1/customers/{world.customer_a.id}"
    tree = client.get(f"{base}/hierarchy/").json()
    assert sorted(org["counts"]["devices"] for org in tree["organizations"]) == [1, 5]
    assert {org["instance_id"] for org in tree["organizations"]} == {str(second.id), str(synced["inst"].id)}
    assert client.get(f"{base}/groups/51/network/").status_code == 400
    first = client.get(f"{base}/groups/51/network/", {"instance": str(synced["inst"].id)})
    assert first.status_code == 200 and first.json()["counts"]["devices"] == 3
    other = client.get(f"{base}/groups/51/network/", {"instance": str(second.id)})
    assert other.status_code == 200 and other.json()["counts"]["devices"] == 1
    assert client.get(f"{base}/groups/51/network/", {"instance": "invalid"}).status_code == 404
    assert (
        world.client(world.engineer_b).get(f"{base}/groups/51/network/", {"instance": str(second.id)}).status_code
        == 404
    )

    ExpectedSubnet.objects.create(
        customer=world.customer_a,
        scope_type="group",
        scope_external_id="51",
        cidr="10.0.1.0/24",
        state="approved",
        reason="Legacy rule without source identity",
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    net = client.get(f"{base}/groups/51/network/", {"instance": str(synced["inst"].id)}).json()
    assert net["expected_subnets"] == []
    assert net["addresses_not_evaluated_against_expectation"] > 0


@pytest.mark.parametrize("search", ["10.0.1.10", "00:AA:00:11:00:99"])
def test_network_search_export_matches_list(world, synced, django_capture_on_commit_callbacks, search):  # noqa: F811
    client = world.client(world.engineer_a)
    base = f"/api/v1/customers/{world.customer_a.id}"
    listing = client.get(f"{base}/assets/", {"search": search}).json()
    assert listing["count"] > 0
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"{base}/reports/", {"report_type": "asset_inventory", "filters": {"search": search}})
    assert response.status_code == 202
    download = client.get(f"/api/v1/reports/{response.json()['id']}/download/")
    assert download.status_code == 200
    rows = list(csv.reader(io.StringIO(b"".join(download.streaming_content).decode("utf-8-sig"))))
    header = next(i for i, row in enumerate(rows) if row and row[0] == "device_id")
    assert [row[0] for row in rows[header + 1 :]] == [row["external_id"] for row in listing["results"]]


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
def test_network_report_formats_and_scope(world, synced, django_capture_on_commit_callbacks, fmt):  # noqa: F811
    client = world.client(world.engineer_a)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            f"/api/v1/customers/{world.customer_a.id}/reports/",
            {
                "report_type": "group_network",
                "format": fmt,
                "filters": {"group_id": "51", "instance": str(synced["inst"].id)},
            },
        )
    assert response.status_code == 202, response.content
    result = client.get(f"/api/v1/reports/{response.json()['id']}/").json()
    assert result["state"] == "completed" and result["row_count"] > 0
    download = client.get(f"/api/v1/reports/{result['id']}/download/")
    assert download.status_code == 200
    content = b"".join(download.streaming_content)
    if fmt == "csv":
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        header = next(i for i, row in enumerate(rows) if row and row[0] == "device_id")
        assert all(len(row) == 19 for row in rows[header:])
        assert {row[2] for row in rows[header + 1 :]} == {str(synced["inst"].id)}
        assert {row[9] for row in rows[header + 1 :]} >= {"10.0.1.10", "10.0.2.5", "172.20.1.1"}
    elif fmt == "xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(content), read_only=True)
        assert len(list(workbook["Data"].values)) == result["row_count"] + 1
        workbook.close()
    else:
        from pypdf import PdfReader

        assert len(PdfReader(io.BytesIO(content)).pages) > 0
    assert world.client(world.engineer_b).get(f"/api/v1/reports/{result['id']}/download/").status_code == 404


def test_network_report_preserves_missing_sections(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    client = world.client(world.engineer_a)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            f"/api/v1/customers/{world.customer_a.id}/reports/",
            {
                "report_type": "group_network",
                "filters": {"group_id": "61"},
            },
        )
    download = client.get(f"/api/v1/reports/{response.json()['id']}/download/")
    assert download.status_code == 200
    rows = list(csv.reader(io.StringIO(b"".join(download.streaming_content).decode("utf-8-sig"))))
    header = next(i for i, row in enumerate(rows) if row and row[0] == "device_id")
    assert len(rows[header + 1 :]) == 1
    assert rows[header + 1][6] == "not_collected"
