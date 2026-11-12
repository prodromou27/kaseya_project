"""Report job + artifact foundation (exercised by the P0 gate). REP-02 formula injection, idempotency, expiry."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.core.csv_safety import neutralize_cell
from apps.reporting.models import ReportArtifact, ReportRun
from apps.reporting.services import generate, storage_path

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('=HYPERLINK("http://evil")', '\'=HYPERLINK("http://evil")'),
        ("+SUM(A1)", "'+SUM(A1)"),
        ("-2+3", "'-2+3"),
        ("@cmd", "'@cmd"),
        ("\tTAB", "'\tTAB"),
        ("\rCR", "'\rCR"),
        ("normal", "normal"),
        (None, ""),
        (42, "42"),
    ],
)
def test_neutralize_cell(raw, expected):
    assert neutralize_cell(raw) == expected


def _request(client, customer, capture, **filters):
    with capture(execute=True):
        resp = client.post(
            f"/api/v1/customers/{customer.id}/reports/", {"report_type": "customer_audit_log", "filters": filters}
        )
    assert resp.status_code == 202, resp.content
    return ReportRun.objects.get(pk=resp.json()["id"])


def test_audit_csv_report_end_to_end(world, django_capture_on_commit_callbacks):
    record_event(action="=cmd|' /C calc'!A0", outcome="success", customer=world.customer_a, actor_label="@evil")
    record_event(action="other.customer", outcome="success", customer=world.customer_b)
    client = world.client(world.admin_a)
    run = _request(client, world.customer_a, django_capture_on_commit_callbacks)
    run.refresh_from_db()
    assert run.state == "completed" and run.row_count >= 1

    resp = client.get(f"/api/v1/reports/{run.id}/download/")
    assert resp.status_code == 200
    body = b"".join(resp.streaming_content)
    assert hashlib.sha256(body).hexdigest() == resp["X-Content-SHA256"] == run.artifact.sha256
    assert "attachment" in resp["Content-Disposition"] and "ACME_customer_audit_log" in resp["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
    assert ["# Customer: Acme Ltd (ACME)"] in rows
    header = rows.index(["created_at_utc", "action", "outcome", "actor", "target_type", "target_id", "request_id"])
    assert all(r[0].startswith("# ") for r in rows[:header])
    data_rows = rows[header + 1 :]
    actions = [r[1] for r in data_rows]
    assert "'=cmd|' /C calc'!A0" in actions  # neutralised
    assert "other.customer" not in actions  # scoped
    assert all(not r[3].startswith("@") for r in data_rows)
    assert AuditEvent.objects.filter(action="report.downloaded", target_id=str(run.id)).exists()


def test_report_filters_applied(world, django_capture_on_commit_callbacks):
    record_event(action="alpha.one", outcome="success", customer=world.customer_a)
    record_event(action="beta.two", outcome="failure", customer=world.customer_a)
    run = _request(world.client(world.admin_a), world.customer_a, django_capture_on_commit_callbacks, outcome="failure")
    run.refresh_from_db()
    assert run.row_count == 1


def test_generation_is_idempotent(world, django_capture_on_commit_callbacks):
    run = _request(world.client(world.admin_a), world.customer_a, django_capture_on_commit_callbacks)
    again = generate(str(run.id))
    assert again.state == "completed"
    assert ReportArtifact.objects.filter(report_run=run).count() == 1


def test_expired_artifact_not_downloadable(world, django_capture_on_commit_callbacks):
    client = world.client(world.admin_a)
    run = _request(client, world.customer_a, django_capture_on_commit_callbacks)
    ReportArtifact.objects.filter(report_run=run).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.get(f"/api/v1/reports/{run.id}/download/").status_code == 404
    assert client.get(f"/api/v1/reports/{run.id}/").json()["download_available"] is False


def test_row_limit_fails_safely(world, settings, django_capture_on_commit_callbacks):
    settings.REPORT_MAX_ROWS = 1
    for i in range(3):
        record_event(action=f"a.{i}", outcome="success", customer=world.customer_a)
    run = _request(world.client(world.admin_a), world.customer_a, django_capture_on_commit_callbacks)
    run.refresh_from_db()
    assert run.state == "failed" and run.error_code == "row_limit_exceeded"


def test_storage_path_rejects_traversal(settings):
    with pytest.raises(ValueError):
        storage_path("../../etc/passwd")
    assert storage_path("0" * 32 + ".csv").name == "0" * 32 + ".csv"


def test_response_never_exposes_storage_path(world, django_capture_on_commit_callbacks):
    client = world.client(world.admin_a)
    run = _request(client, world.customer_a, django_capture_on_commit_callbacks)
    body = client.get(f"/api/v1/reports/{run.id}/").content.decode()
    assert run.artifact.storage_key not in body and str(settings_dir(run)) not in body


def settings_dir(run: ReportRun) -> str:
    return str(storage_path(run.artifact.storage_key).parent)
