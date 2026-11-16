"""CRM-02 monthly customer scorecard: measures across modules, honest 30-day comparison, scoped CSV output."""

from __future__ import annotations

import csv
import io
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.integrations.models import DatasetGeneration

from .test_p1_api import do_sync, synced, vsa_assets  # noqa: F401

pytestmark = pytest.mark.django_db


def generate(world, capture, user=None):
    with capture(execute=True):
        resp = ((user and world.client(user)) or world.client(world.engineer_a)).post(
            f"/api/v1/customers/{world.customer_a.id}/reports/",
            {"report_type": "customer_scorecard", "format": "csv", "filters": {}},
            format="json",
        )
    assert resp.status_code == 202, resp.content
    raw = b"".join(
        world.client(world.engineer_a).get(f"/api/v1/reports/{resp.json()['id']}/download/").streaming_content
    )
    lines = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    header = next(i for i, r in enumerate(lines) if r and not r[0].startswith("# "))
    return lines[header], {(r[0], r[1]): r for r in lines[header + 1 :]}


def test_scorecard_covers_every_area_without_inventing_history(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    header, rows = generate(world, django_capture_on_commit_callbacks)
    assert header == ["section", "measure", "value", "previous_value", "previous_as_of", "change", "notes"]
    assert {s for s, _ in rows} == {
        "Inventory",
        "Health",
        "Patching",
        "Software",
        "Lifecycle",
        "Servers",
        "Compliance",
        "Network",
    }
    devices = rows[("Inventory", "Devices")]
    assert devices[2] == "6" and devices[3] == "" and devices[5] == ""  # one snapshot only: no comparison
    assert rows[("Compliance", "Baselines")][6] == "No compliance baseline defined"


def test_scorecard_compares_with_the_snapshot_about_30_days_earlier(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    old = DatasetGeneration.objects.get(mapping=synced["mapping_a"], is_current=True)
    assert do_sync(synced["mapping_a"], world.engineer_a, vsa_assets(8, 11, "a")).state == "completed"
    DatasetGeneration.objects.filter(pk=old.pk).update(published_at=timezone.now() - timedelta(days=35))
    _, rows = generate(world, django_capture_on_commit_callbacks)
    devices = rows[("Inventory", "Devices")]
    assert devices[2] == "8" and devices[3] == "6" and devices[5] == "up 2" and devices[4]


def test_scorecard_is_scoped_and_needs_export(world, synced):  # noqa: F811
    url = f"/api/v1/customers/{world.customer_a.id}/reports/"
    body = {"report_type": "customer_scorecard", "format": "csv", "filters": {}}
    assert world.client(world.engineer_b).post(url, body, format="json").status_code == 404
    assert world.client(world.viewer_a).post(url, body, format="json").status_code in (403, 404)
    assert (
        world.client(world.engineer_a).post(url, {**body, "filters": {"customer": "B"}}, format="json").status_code
        == 400
    )
