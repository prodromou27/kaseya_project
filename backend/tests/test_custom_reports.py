"""Custom report builder: allowlisted sources/fields/operators, preview, and generation through the report pipeline."""

from __future__ import annotations

import csv
import io

import pytest

from .test_p1_api import approve_chrome, reviewer, synced  # noqa: F401

pytestmark = pytest.mark.django_db


def preview(world, spec, user=None):
    return world.client(user or world.engineer_a).post(
        f"/api/v1/customers/{world.customer_a.id}/custom-reports/preview/", spec, format="json"
    )


def test_catalog_lists_sources_fields_and_operators(world):
    data = world.client(world.viewer_a).get("/api/v1/report-sources/").json()
    sources = {s["key"]: s for s in data}
    assert {"devices", "health", "software", "os_updates", "compliance", "third_party", "subnets"} <= set(sources)
    fields = {f["key"]: f for f in sources["software"]["fields"]}
    assert fields["version_state"]["type"] == "enum" and "outdated" in fields["version_state"]["values"]
    assert "contains" in fields["program"]["operators"]
    templates = world.client(world.viewer_a).get("/api/v1/report-templates/").json()
    assert next(t for t in templates if t["key"] == "custom")["builder"] is True


def test_preview_filters_sorts_and_selects_columns(world, synced):  # noqa: F811
    spec = {
        "source": "devices",
        "columns": ["hostname", "os_name"],
        "conditions": [{"field": "hostname", "op": "starts_with", "value": "A-PC"}],
        "sort": "hostname",
        "descending": True,
    }
    body = preview(world, spec).json()
    assert [c["label"] for c in body["columns"]] == ["Device", "Operating system"]
    assert body["count"] == 5  # A-PC1..A-PC5 (A-PC0 was renamed to hostile text in the fixture)
    assert [r[0] for r in body["rows"]] == sorted((r[0] for r in body["rows"]), reverse=True)
    any_match = {
        **spec,
        "match": "any",
        "conditions": [*spec["conditions"], {"field": "os_name", "op": "contains", "value": "windows"}],
    }
    assert preview(world, any_match).json()["count"] == 6


def test_enum_and_number_conditions_on_software(world, synced, reviewer, django_capture_on_commit_callbacks):  # noqa: F811
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks)
    spec = {"source": "software", "conditions": [{"field": "version_state", "op": "in", "value": ["outdated"]}]}
    body = preview(world, spec).json()
    assert body["count"] == 3 and all("130.0.1.1" in r for r in body["rows"])
    health = preview(
        world,
        {
            "source": "health",
            "columns": ["hostname", "days_since_seen"],
            "conditions": [{"field": "days_since_seen", "op": "gte", "value": 0}],
        },
    ).json()
    assert health["count"] == 6


@pytest.mark.parametrize(
    "spec",
    [
        {"source": "passwords"},
        {"source": "devices", "columns": ["hostname", "secret"]},
        {"source": "devices", "columns": ["hostname", "hostname"]},
        {"source": "devices", "conditions": [{"field": "hostname", "op": "regex", "value": ".*"}]},
        {"source": "devices", "conditions": [{"field": "days_since_seen", "op": "gt", "value": "1; DROP TABLE"}]},
        {"source": "health", "conditions": [{"field": "disk", "op": "in", "value": ["melted"]}]},
        {"source": "devices", "conditions": [{"field": "last_seen", "op": "before", "value": "yesterday"}]},
        {"source": "devices", "sort": "password"},
    ],
)
def test_invalid_specifications_are_rejected(world, synced, spec):  # noqa: F811
    assert preview(world, spec).status_code == 400


def test_custom_report_generates_csv_with_chosen_columns(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    spec = {
        "source": "devices",
        "columns": ["hostname", "os_name"],
        "title": "Windows estate",
        "conditions": [{"field": "os_name", "op": "contains", "value": "windows 11"}],
    }
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.engineer_a).post(
            f"/api/v1/customers/{world.customer_a.id}/reports/",
            {"report_type": "custom", "format": "csv", "filters": spec},
            format="json",
        )
    assert resp.status_code == 202, resp.content
    run = world.client(world.engineer_a).get(f"/api/v1/reports/{resp.json()['id']}/").json()
    assert run["title"] == "Windows estate" and run["state"] == "completed"
    raw = b"".join(
        world.client(world.engineer_a).get(f"/api/v1/reports/{resp.json()['id']}/download/").streaming_content
    )
    lines = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    header = next(i for i, r in enumerate(lines) if r and not r[0].startswith("# "))
    assert lines[header] == ["Device", "Operating system"]
    assert len(lines[header + 1 :]) == 6
    assert any("Windows estate" in r[0] for r in lines[:header])


def test_preview_is_customer_scoped(world, synced):  # noqa: F811
    assert preview(world, {"source": "devices"}, user=world.viewer_a).status_code == 404  # no export capability
    assert preview(world, {"source": "devices"}, user=world.engineer_b).status_code == 404
    b = (
        world.client(world.engineer_b)
        .post(f"/api/v1/customers/{world.customer_b.id}/custom-reports/preview/", {"source": "devices"}, format="json")
        .json()
    )
    assert b["count"] == 4 and all(not r[0].startswith("A-") for r in b["rows"])
