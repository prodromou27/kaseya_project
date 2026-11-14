"""LIST-02: searched populations, complete coverage and pinned customer-scoped exports. Fixtures only."""


# ruff: noqa: F811

import csv
import io

import pytest

from apps.inventory.models import Asset
from apps.patching.models import PatchObservation
from apps.reporting.models import ReportRun
from apps.reporting.registry import REPORT_TYPES

from .test_p2_reporting import devices, do_sync, download, env, request  # noqa: F401

pytestmark = pytest.mark.django_db


def rows(raw):
    parsed = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    header = next(i for i, row in enumerate(parsed) if row and row[0] == "device_id")
    return [dict(zip(parsed[header], row, strict=True)) for row in parsed[header + 1 :]]


@pytest.mark.parametrize(
    ("report_type", "route", "search"),
    [
        ("software_compliance", "software", "A1"),
        ("software_compliance", "software", "1.0"),
        ("os_updates", "os-updates", "Fixture update"),
        ("os_updates", "os-updates", "A1"),
    ],
)
def test_search_matches_scoped_export(world, env, django_capture_on_commit_callbacks, report_type, route, search):
    client = world.client(world.engineer_a)
    listed = client.get(f"/api/v1/customers/{world.customer_a.id}/{route}/", {"search": search}).json()
    assert listed["count"] > 0
    run = request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        report_type,
        filters={"search": search},
    )
    exported = rows(download(world, world.engineer_a, run["id"]))
    assert len(exported) == listed["count"]
    expected_ids = set(
        Asset.objects.filter(
            customer=world.customer_a, pk__in=[row["asset_id"] for row in listed["results"]]
        ).values_list("external_id", flat=True)
    )
    assert {row["device_id"] for row in exported} == expected_ids
    assert (
        world.client(world.engineer_b)
        .get(f"/api/v1/customers/{world.customer_a.id}/{route}/", {"search": search})
        .status_code
        == 404
    )


def test_coverage_paging_past_200_and_source_identity(world, env, django_capture_on_commit_callbacks):
    assert do_sync(env["ma"], world.engineer_a, devices(11, "large", 205)).state == "completed"
    client = world.client(world.engineer_a)
    url = f"/api/v1/customers/{world.customer_a.id}/os-updates/devices/"
    found = []
    for page in [1, 2, 3]:
        data = client.get(url, {"page": page, "page_size": 100}).json()
        assert data["count"] == 205
        found.extend(row["asset_id"] for row in data["results"])
    assert len(set(found)) == 205
    assert client.get(url, {"search": "LARGE204"}).json()["count"] == 1
    assert client.get(url, {"search": "B1"}).json()["count"] == 0
    run = request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        "os_update_coverage",
        filters={"search": "LARGE204", "available_status": "collected"},
    )
    exported = rows(download(world, world.engineer_a, run["id"]))
    assert len(exported) == 1 and exported[0]["hostname"] == "LARGE204"
    assert exported[0]["source_instance_id"] == str(env["inst"].id)


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
def test_coverage_formats_preserve_unknown_and_historical_population(
    world,
    env,
    django_capture_on_commit_callbacks,
    fmt,
):
    obj = PatchObservation.objects.filter(customer=world.customer_a).first()
    PatchObservation.objects.filter(pk=obj.pk).update(available_status="not_collected", available_count=None)
    run = request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        "os_update_coverage",
        fmt,
        {"available_status": "not_collected"},
    )
    raw = download(world, world.engineer_a, run["id"])
    stored = ReportRun.objects.get(pk=run["id"])
    assert stored.row_count == 1 and stored.data_basis == "fixture"
    if fmt == "csv":
        row = rows(raw)[0]
        assert row["available_status"] == "not_collected" and row["available_count"] == ""
    assert world.client(world.engineer_b).get(f"/api/v1/reports/{run['id']}/download/").status_code == 404
    report = REPORT_TYPES["os_update_coverage"]
    pins = report.pin(world.customer_a, None)
    original = list(report.rows(world.customer_a, {"available_status": "not_collected"}, pins))
    assert do_sync(env["ma"], world.engineer_a, devices(11, "next", 4)).state == "completed"
    assert list(report.rows(world.customer_a, {"available_status": "not_collected"}, pins)) == original


@pytest.mark.parametrize("filters", [{"available_status": "healthy"}, {"search": "x" * 101}, {"customer": "other"}])
def test_coverage_rejects_malformed_report_filters(world, env, django_capture_on_commit_callbacks, filters):
    request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        "os_update_coverage",
        filters=filters,
        expect=400,
    )
