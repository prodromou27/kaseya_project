"""CRM-03: reports evaluated at generation time keep their rows, so regeneration reproduces the same figures."""

from __future__ import annotations

import csv
import io

import pytest

from apps.compliance.models import BaselineRule, ComplianceBaseline
from apps.reporting.models import FrozenReportRows

from .test_p1_api import synced  # noqa: F401

pytestmark = pytest.mark.django_db

SPEC = {"source": "compliance", "columns": ["hostname", "status", "failing"], "sort": "hostname"}


def rows_of(world, run_id):
    raw = b"".join(world.client(world.engineer_a).get(f"/api/v1/reports/{run_id}/download/").streaming_content)
    lines = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    header = next(i for i, r in enumerate(lines) if r and not r[0].startswith("# "))
    return [r[0] for r in lines[:header]], lines[header + 1 :]


def request(world, capture, body):
    with capture(execute=True):
        resp = world.client(world.engineer_a).post(
            f"/api/v1/customers/{world.customer_a.id}/reports/", body, format="json"
        )
    assert resp.status_code == 202, resp.content
    return resp.json()["id"]


def regenerate(world, capture, run_id):
    with capture(execute=True):
        resp = world.client(world.engineer_a).post(f"/api/v1/reports/{run_id}/regenerate/")
    assert resp.status_code == 202, resp.content
    return resp.json()["id"]


def test_regeneration_reproduces_live_evaluated_figures(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    baseline = ComplianceBaseline.objects.create(customer=world.customer_a, name="Std", created_by=world.admin_a)
    rule = BaselineRule.objects.create(baseline=baseline, kind="forbidden_software", params={"name": "Contoso"})
    body = {"report_type": "custom", "format": "csv", "filters": SPEC}
    first = request(world, django_capture_on_commit_callbacks, body)
    _, original = rows_of(world, first)
    assert original and all(r[1] == "fail" for r in original)
    assert FrozenReportRows.objects.filter(report_run_id=first).exists()

    # The baseline changes afterwards: every device would now pass.
    rule.params = {"name": "Nothing installed anywhere"}
    rule.save()
    provenance, again = rows_of(world, regenerate(world, django_capture_on_commit_callbacks, first))
    assert again == original
    assert any(f"Reproduced from the figures evaluated for run {first}" in p for p in provenance)

    _, fresh = rows_of(world, request(world, django_capture_on_commit_callbacks, body))
    assert all(r[1] == "pass" for r in fresh)  # a new report reflects the current baseline


def test_snapshot_reports_are_not_frozen(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    run = request(
        world,
        django_capture_on_commit_callbacks,
        {"report_type": "custom", "format": "csv", "filters": {"source": "devices"}},
    )
    assert not FrozenReportRows.objects.filter(report_run_id=run).exists()
    scorecard = request(
        world, django_capture_on_commit_callbacks, {"report_type": "customer_scorecard", "format": "csv", "filters": {}}
    )
    frozen = FrozenReportRows.objects.get(report_run_id=scorecard)
    assert frozen.customer_id == world.customer_a.id and frozen.rows
