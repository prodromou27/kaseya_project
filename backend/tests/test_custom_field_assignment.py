"""CFA: VSA X custom field assignment - discovery, matching, import, preview, gated writes, read-back, RBAC, audit."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook, load_workbook

from apps.audit.models import AuditEvent
from apps.customfields import jobs
from apps.customfields.models import AssignmentItem, AssignmentJob, CustomFieldDefinition
from apps.integrations.vsa import fixtures
from apps.integrations.vsa.cf_writer import VsaCustomFieldWriter
from apps.inventory.queries import current_observations

from .test_automation import demo  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    fixtures.FIXTURE_CUSTOM_FIELDS.clear()
    monkeypatch.setattr(jobs, "sleep", lambda s: None)
    yield
    fixtures.FIXTURE_CUSTOM_FIELDS.clear()


def base(world):
    return f"/api/v1/customers/{world.customer_a.id}"


@pytest.fixture
def ready(world, demo, settings, django_capture_on_commit_callbacks):  # noqa: F811
    """Writes switched on, definitions read, PatchRing/Cost Center/Encryption Exempt editable."""
    settings.VSA_CUSTOM_FIELD_WRITES_ENABLED = True
    demo.custom_field_writes_enabled = True
    demo.save()
    assert world.client(world.engineer_a).post(f"{base(world)}/custom-fields/refresh/").status_code == 200
    admin = world.client(world.super_admin)
    for name in ("PatchRing", "Cost Center", "Encryption Exempt"):
        d = CustomFieldDefinition.objects.get(name=name)
        assert admin.patch(f"/api/v1/custom-field-definitions/{d.id}/", {"portal_writable": True}).status_code == 200
    return demo


def ring(world):
    return CustomFieldDefinition.objects.get(name="PatchRing")


def workstations(world, n=None):
    rows = [
        o
        for o in current_observations(world.customer_a.id).order_by("hostname")
        if "server" not in o.os_name.casefold()
    ]
    return rows[:n] if n else rows


def run_job(world, client, payload, capture, *, ack=False, applier=None):
    """Create + preview as ``client``, confirm as an administrator (eager Celery). Returns the job after execution."""
    resp = client.post(f"{base(world)}/custom-field-jobs/", payload, format="json")
    assert resp.status_code == 201, resp.content
    job = resp.json()
    with capture(execute=True):
        assert client.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/").status_code == 200
    with capture(execute=True):
        resp = (applier or world.client(world.admin_a)).post(
            f"{base(world)}/custom-field-jobs/{job['id']}/confirm/",
            {"confirm": True, "acknowledge_overwrite": ack},
            format="json",
        )
    assert resp.status_code == 200, resp.content
    return client.get(f"{base(world)}/custom-field-jobs/{job['id']}/").json()


def items(world, client, job_id, **params):
    return client.get(f"{base(world)}/custom-field-jobs/{job_id}/items/", params).json()["results"]


# ------------------------------------------------------------------------------------------------ discovery


def test_definitions_are_read_and_only_eligible_fields_can_be_made_editable(world, ready):
    fields = {f["name"]: f for f in world.client(world.viewer_a).get(f"{base(world)}/custom-fields/").json()}
    assert fields["PatchRing"]["editable"] and fields["PatchRing"]["contexts"] == ["Organization", "Device"]
    assert fields["PatchRing"]["default_value"] == "Ring 2" and fields["Cost Center"]["type"] == "Number"
    assert fields["Rack"]["reason"] == "Not enabled for editing in the portal"
    assert fields["Script Managed Tag"]["reason"] == "Read-only in VSA X"
    assert fields["Contract tier"]["reason"] == "Not available for devices"
    assert fields["Old Project Code"]["reason"] == "Expired"
    assert fields["Local Admin Password"]["reason"].startswith("Credential-like")
    admin = world.client(world.super_admin)
    for name in ("Script Managed Tag", "Contract tier", "Old Project Code", "Local Admin Password"):
        d = CustomFieldDefinition.objects.get(name=name)
        assert admin.patch(f"/api/v1/custom-field-definitions/{d.id}/", {"portal_writable": True}).status_code == 400
    # Only system administrators change field settings.
    d = CustomFieldDefinition.objects.get(name="Rack")
    for user in (world.admin_a, world.engineer_a):
        assert (
            world.client(user).patch(f"/api/v1/custom-field-definitions/{d.id}/", {"portal_writable": True}).status_code
            == 403
        )


# ------------------------------------------------------------------------------------------------ end to end


def test_selected_devices_assign_update_skip_with_read_back(world, ready, django_capture_on_commit_callbacks):
    ws = workstations(world, 6)
    eng = world.client(world.engineer_a)
    body = run_job(
        world,
        eng,
        {"field": str(ring(world).id), "value": "Ring 0", "assets": [str(o.asset_id) for o in ws]},
        django_capture_on_commit_callbacks,
        ack=True,
    )
    assert body["state"] == "completed", body
    rows = items(world, eng, body["id"])
    by_host = {r["hostname"]: r for r in rows}
    # Index 0 (divisible by 5) had a device-level "Ring 1": update; the others inherit "Ring 2": assign.
    preset = [r for r in rows if r["current_source"] == "device"]
    assert preset and all(r["action"] == "update" and r["current_value"] == "Ring 1" for r in preset)
    inherited = [r for r in rows if r["current_source"] == "inherited"]
    assert inherited and all(r["action"] == "assign" and r["current_value"] == "Ring 2" for r in inherited)
    assert all(r["result"] == "verified" and r["final_value"] == "Ring 0" for r in by_host.values())
    # VSA X (fixture) now holds the value on exactly these devices.
    assert {k[2] for k in fixtures.FIXTURE_CUSTOM_FIELDS} == {r["device_external_id"] for r in rows}

    # Same request again: everything is already correct and nothing is written.
    resp = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 0", "assets": [str(o.asset_id) for o in ws]},
        format="json",
    )
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{resp.json()['id']}/preview/")
    again = eng.get(f"{base(world)}/custom-field-jobs/{resp.json()['id']}/").json()
    assert again["counts"]["action"] == {"skip": 6} and again["counts"]["to_change"] == 0
    assert (
        world.client(world.admin_a)
        .post(f"{base(world)}/custom-field-jobs/{again['id']}/confirm/", {"confirm": True}, format="json")
        .status_code
        == 400
    )

    events = set(AuditEvent.objects.filter(action__startswith="custom_field.").values_list("action", flat=True))
    assert {
        "custom_field.job_created",
        "custom_field.previewed",
        "custom_field.confirmed",
        "custom_field.assignment",
        "custom_field.execution_finished",
    } <= events
    one = AuditEvent.objects.filter(action="custom_field.assignment").first()
    assert one.metadata["requested_value"] == "Ring 0" and one.metadata["field"] == "PatchRing"
    assert one.actor == world.admin_a  # the administrator who applied it
    job = AssignmentJob.objects.get(pk=body["id"])
    assert job.created_by == world.engineer_a and job.confirmed_by == world.admin_a


def test_overwrite_needs_acknowledgement(world, ready, django_capture_on_commit_callbacks):
    ws = workstations(world, 1)
    fixtures.FIXTURE_CUSTOM_FIELDS[(str(ready.id), "901", str(ws[0].asset.external_id))] = "Ring 1"  # set on the device
    eng = world.client(world.engineer_a)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 3", "assets": [str(ws[0].asset_id)]},
        format="json",
    ).json()
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    resp = world.client(world.admin_a).post(
        f"{base(world)}/custom-field-jobs/{job['id']}/confirm/", {"confirm": True}, format="json"
    )
    assert resp.status_code == 400 and "acknowledge_overwrite" in resp.json()["error"]["details"]


def test_pasted_list_matching_classes(world, ready):
    ws = workstations(world, 3)
    server = next(o for o in current_observations(world.customer_a.id) if "server" in o.os_name.casefold())
    text = "\n".join(
        [
            ws[0].hostname,
            ws[0].hostname.lower(),  # duplicate input
            f"{ws[1].hostname}, {server.hostname}",
            "NO-SUCH-PC",
            "bad name!",
            str(ws[2].asset.external_id),
        ]
    )
    job = (
        world.client(world.engineer_a)
        .post(
            f"{base(world)}/custom-field-jobs/",
            {"field": str(ring(world).id), "value": "Ring 0", "source": "list", "text": text},
            format="json",
        )
        .json()
    )
    got = [(r["input_identifier"], r["match_status"]) for r in items(world, world.client(world.engineer_a), job["id"])]
    assert got == [
        (ws[0].hostname, "matched"),
        (ws[0].hostname.lower(), "duplicate"),
        (ws[1].hostname, "matched"),
        (server.hostname, "unsupported"),
        ("NO-SUCH-PC", "not_found"),
        ("bad name!", "invalid"),
        (str(ws[2].asset.external_id), "matched"),
    ]
    assert job["counts"]["match"]["matched"] == 3


def test_ambiguous_hostname_needs_a_choice(world, ready):
    ws = workstations(world, 2)
    a, b = ws
    b.hostname = a.hostname  # two devices with the same name
    b.save(update_fields=["hostname"])
    eng = world.client(world.engineer_a)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 0", "source": "list", "text": a.hostname},
        format="json",
    ).json()
    (item,) = items(world, eng, job["id"])
    assert item["match_status"] == "multiple" and len(item["candidates"]) == 2 and not item["included"]
    assert eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/").status_code == 400  # nothing included
    other = str(
        current_observations(world.customer_a.id).exclude(asset_id__in=[a.asset_id, b.asset_id]).first().asset_id
    )
    bad = eng.post(
        f"{base(world)}/custom-field-jobs/{job['id']}/resolve/", {"item": item["id"], "asset": other}, format="json"
    )
    assert bad.status_code == 400
    ok = eng.post(
        f"{base(world)}/custom-field-jobs/{job['id']}/resolve/",
        {"item": item["id"], "asset": str(b.asset_id)},
        format="json",
    )
    assert ok.json()["match_status"] == "matched" and ok.json()["included"]


def test_xlsx_csv_and_txt_imports_with_column_mapping(world, ready):
    ws = workstations(world, 2)
    eng = world.client(world.engineer_a)
    wb = Workbook()
    sheet = wb.active
    sheet.append(["Computer Name", "Serial", "New value"])
    sheet.append([ws[0].hostname, "", "Ring 1"])
    sheet.append(['=HYPERLINK("http://evil.invalid")', "", "Ring 1"])
    buf = io.BytesIO()
    wb.save(buf)
    inspect = eng.post(
        f"{base(world)}/custom-field-jobs/inspect-file/",
        {"file": _upload("devices.xlsx", buf.getvalue())},
        format="multipart",
    ).json()
    assert inspect["columns"] == ["Computer Name", "Serial", "New value"] and inspect["rows"] == 2
    assert inspect["mapping"] == {"hostname": 0, "serial": 1, "value": 2}
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {
            "field": str(ring(world).id),
            "file": _upload("devices.xlsx", buf.getvalue()),
            "mapping": '{"hostname": 0, "value": 2}',
        },
        format="multipart",
    ).json()
    rows = items(world, eng, job["id"])
    assert job["per_device_values"] and job["source"] == "import" and job["source_filename"] == "devices.xlsx"
    assert [r["match_status"] for r in rows] == ["matched", "invalid"]  # the formula cell is never evaluated
    assert rows[0]["requested_value"] == "Ring 1"

    csv_job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {
            "field": str(ring(world).id),
            "value": "Ring 0",
            "file": _upload("d.csv", f"hostname\n{ws[1].hostname}\n{ws[1].hostname}\n".encode()),
            "mapping": '{"hostname": 0}',
        },
        format="multipart",
    ).json()
    assert [r["match_status"] for r in items(world, eng, csv_job["id"])] == ["matched", "duplicate"]
    txt = eng.post(
        f"{base(world)}/custom-field-jobs/inspect-file/",
        {"file": _upload("d.txt", f"{ws[0].hostname}\r\n\r\n{ws[1].hostname}\r\n".encode())},
        format="multipart",
    ).json()
    assert txt["rows"] == 2 and txt["mapping"] == {"hostname": 0}
    macro = eng.post(
        f"{base(world)}/custom-field-jobs/inspect-file/",
        {"file": _upload("x.xlsm", b"PK\x03\x04junk")},
        format="multipart",
    )
    assert macro.status_code == 400


def _upload(name, data):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, data)


# ------------------------------------------------------------------------------------------------ safety


def test_writes_are_off_unless_every_gate_is_set(world, demo, settings, django_capture_on_commit_callbacks):  # noqa: F811
    eng = world.client(world.engineer_a)
    world.client(world.engineer_a).post(f"{base(world)}/custom-fields/refresh/")
    d = CustomFieldDefinition.objects.get(name="PatchRing")
    resp = eng.post(
        f"{base(world)}/custom-field-jobs/", {"field": str(d.id), "value": "Ring 0", "assets": []}, format="json"
    )
    assert resp.status_code == 400  # field not editable yet
    d.portal_writable = True
    d.save()
    ws = workstations(world, 1)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(d.id), "value": "Ring 0", "assets": [str(ws[0].asset_id)]},
        format="json",
    ).json()
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    admin = world.client(world.admin_a)
    settings.VSA_CUSTOM_FIELD_WRITES_ENABLED = False  # the server emergency stop
    confirm = admin.post(
        f"{base(world)}/custom-field-jobs/{job['id']}/confirm/",
        {"confirm": True, "acknowledge_overwrite": True},
        format="json",
    )
    assert confirm.status_code == 400 and "switched off on this server" in str(confirm.json())
    settings.VSA_CUSTOM_FIELD_WRITES_ENABLED = True
    confirm = admin.post(
        f"{base(world)}/custom-field-jobs/{job['id']}/confirm/",
        {"confirm": True, "acknowledge_overwrite": True},
        format="json",
    )
    assert "not enabled for this VSA X integration" in str(confirm.json())
    assert not fixtures.FIXTURE_CUSTOM_FIELDS
    # A live integration also needs a validated route and an API token (a separate write token is optional).
    from apps.integrations.vsa.cf_writer import availability

    demo.is_fixture, demo.custom_field_writes_enabled = False, True
    demo.credential_ref, demo.credential_ciphertext = "", ""
    ok, why = availability(demo)
    assert not ok and why.startswith("The custom field route has not been validated on a test workstation yet.")
    assert "Settings → Integrations → Edit" in why
    demo.custom_field_write_route = "automation/customfields"
    assert availability(demo)[1] == "No VSA X API token is configured for this integration."
    demo.credential_ref = "env:VSA_TOKEN_PROD"
    assert availability(demo) == (True, "")


def test_only_documented_routes_and_body(world, ready):
    from apps.integrations.vsa.cf_writer import path_for

    assert path_for("customfields", "901", "assign") == "/api/v3/customfields/901/assign"
    assert (
        path_for("automation/customfields", "901", "updateAssigned")
        == "/api/v3/automation/customfields/901/updateAssigned"
    )
    for bad in (("customfields", "901", "unassign"), ("other", "901", "assign"), ("customfields", "9/../1", "assign")):
        with pytest.raises(ValueError):
            path_for(*bad)
    transport = fixtures.FixtureCustomFieldWriteTransport(ready)
    writer = VsaCustomFieldWriter(ready, transport=transport)
    device = str(workstations(world, 2)[1].asset.external_id)
    writer.write("901", device, "Ring 5", update=False)
    assert transport.calls == [
        (
            "POST",
            "/api/v3/customfields/901/assign",
            {"ContextType": "Device", "ContextItemId": device, "UseDefaultValue": False, "Value": "Ring 5"},
        )
    ]
    with pytest.raises(ValueError):
        writer.write("901", "../x", "Ring 5", update=False)


def test_failures_timeouts_and_rate_limits(world, ready, django_capture_on_commit_callbacks):
    import requests

    from apps.integrations.vsa.cf_writer import WriteOutcomeUnknown, WriteRejected

    ws = workstations(world, 4)
    eng = world.client(world.engineer_a)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 9", "assets": [str(o.asset_id) for o in ws[1:4]]},
        format="json",
    ).json()
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    jobs.confirm(AssignmentJob.objects.get(pk=job["id"]), world.engineer_a, acknowledge_overwrite=True)

    real = fixtures.FixtureCustomFieldWriteTransport(ready)
    script = iter(["429", "ok", "400", "timeout_applied"])

    class Flaky:
        calls = 0

        def send(self, method, url, **kw):
            Flaky.calls += 1
            step = next(script)
            if step == "429":
                return fixtures.FakeResponse(429)
            if step == "400":
                return fixtures.FakeResponse(400)
            if step == "timeout_applied":
                real.send(method, url, **kw)  # applied, but the answer is lost
                raise requests.Timeout()
            return real.send(method, url, **kw)

    writer = VsaCustomFieldWriter(ready, transport=Flaky())
    done = jobs.execute(job["id"], writer=writer)
    assert done.state == "completed"
    results = [r["result"] for r in items(world, eng, job["id"])]
    assert results == ["verified", "failed", "verified"]  # 429 backed off then succeeded; 400 failed; timeout read back
    failed = items(world, eng, job["id"], result="failed")[0]
    assert failed["error_code"] == "vsa_rejected_400" and failed["http_status"] == 400
    lost = items(world, eng, job["id"])[2]
    assert lost["error_code"].startswith("confirmed_after_timeout")
    assert Flaky.calls == 4
    assert WriteOutcomeUnknown and WriteRejected


def test_concurrent_change_and_interrupted_run_are_never_resent(world, ready, django_capture_on_commit_callbacks):
    ws = workstations(world, 3)
    eng = world.client(world.engineer_a)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 7", "assets": [str(o.asset_id) for o in ws[1:3]]},
        format="json",
    ).json()
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    jobs.confirm(AssignmentJob.objects.get(pk=job["id"]), world.engineer_a, acknowledge_overwrite=True)
    first, second = AssignmentItem.objects.filter(job_id=job["id"]).order_by("position")
    # Someone sets the first device in VSA X after the preview; the second was mid-send when a worker died.
    fixtures.FIXTURE_CUSTOM_FIELDS[(str(ready.id), "901", first.device_external_id)] = "Ring 4"
    second.result = AssignmentItem.Result.SENDING
    second.save()
    AssignmentJob.objects.filter(pk=job["id"]).update(state="running", heartbeat_at=None)
    transport = fixtures.FixtureCustomFieldWriteTransport(ready)
    jobs.execute(job["id"], writer=VsaCustomFieldWriter(ready, transport=transport))
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.result, first.error_code, first.final_value) == ("skipped", "changed_since_preview", "Ring 4")
    assert second.result == "unknown"  # not resent; read-back shows it was not applied
    assert transport.calls == []


def test_cancel_and_duplicate_delivery(world, ready, django_capture_on_commit_callbacks):
    ws = workstations(world, 3)
    eng = world.client(world.engineer_a)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 7", "assets": [str(o.asset_id) for o in ws[1:3]]},
        format="json",
    ).json()
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    jobs.confirm(AssignmentJob.objects.get(pk=job["id"]), world.engineer_a, acknowledge_overwrite=True)
    assert eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/cancel/").json()["cancel_requested"]
    done = jobs.execute(job["id"])
    assert done.state == "cancelled" and not fixtures.FIXTURE_CUSTOM_FIELDS
    assert set(AssignmentItem.objects.filter(job_id=job["id"]).values_list("result", flat=True)) == {"cancelled"}
    assert jobs.execute(job["id"]).state == "cancelled"  # a second delivery does nothing
    assert eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/retry/").status_code == 404  # administrators only
    retry = world.client(world.admin_a).post(f"{base(world)}/custom-field-jobs/{job['id']}/retry/")
    assert retry.status_code == 201 and retry.json()["state"] == "draft" and retry.json()["counts"]["items"] == 2


def test_permissions_bulk_limit_approval_and_tenant_isolation(
    world, ready, settings, django_capture_on_commit_callbacks
):
    settings.CUSTOM_FIELD_ENGINEER_MAX_DEVICES = 1
    ws = workstations(world, 3)
    payload = {"field": str(ring(world).id), "value": "Ring 0", "assets": [str(o.asset_id) for o in ws[1:3]]}
    assert (
        world.client(world.viewer_a).post(f"{base(world)}/custom-field-jobs/", payload, format="json").status_code
        == 404
    )
    assert world.client(world.engineer_b).get(f"{base(world)}/custom-field-jobs/").status_code == 404
    eng = world.client(world.engineer_a)
    job = eng.post(f"{base(world)}/custom-field-jobs/", payload, format="json").json()
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    # Engineers prepare and preview; only administrators apply.
    applied = eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/confirm/", {"confirm": True}, format="json")
    assert applied.status_code == 404 and not fixtures.FIXTURE_CUSTOM_FIELDS
    assert AssignmentJob.objects.get(pk=job["id"]).state == "previewed"

    # A customer administrator may; above the approval threshold a different administrator approves.
    ready.custom_field_approval_threshold = 1
    ready.save()
    admin = world.client(world.admin_a)
    with django_capture_on_commit_callbacks(execute=True):
        body = admin.post(
            f"{base(world)}/custom-field-jobs/{job['id']}/confirm/", {"confirm": True}, format="json"
        ).json()
    assert body["state"] == "awaiting_approval" and not fixtures.FIXTURE_CUSTOM_FIELDS
    assert admin.post(f"{base(world)}/custom-field-jobs/{job['id']}/approve/").status_code == 403  # own job
    assert eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/approve/").status_code == 404  # engineers cannot
    with django_capture_on_commit_callbacks(execute=True):
        approved = world.client(world.super_admin).post(f"{base(world)}/custom-field-jobs/{job['id']}/approve/")
    assert approved.status_code == 200
    assert AssignmentJob.objects.get(pk=job["id"]).state == "completed" and len(fixtures.FIXTURE_CUSTOM_FIELDS) == 2

    # Another customer's devices or field cannot be used, even by ID.
    foreign = world.client(world.engineer_b).post(
        f"/api/v1/customers/{world.customer_b.id}/custom-field-jobs/", payload, format="json"
    )
    assert foreign.status_code == 400


def test_report_has_all_sheets_and_neutralised_cells(world, ready, django_capture_on_commit_callbacks):
    ws = workstations(world, 2)
    eng = world.client(world.engineer_a)
    body = run_job(
        world,
        eng,
        {"field": str(ring(world).id), "value": "=cmd|' /C calc'!A0", "assets": [str(o.asset_id) for o in ws[1:2]]},
        django_capture_on_commit_callbacks,
    )
    resp = eng.get(f"{base(world)}/custom-field-jobs/{body['id']}/report/", {"type": "xlsx"})
    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["Summary", "Successful", "Skipped", "Failed", "Not found", "Ambiguous"]
    success = list(wb["Successful"].values)
    assert len(success) == 2 and success[1][11].startswith("'=")
    csv = eng.get(f"{base(world)}/custom-field-jobs/{body['id']}/report/", {"type": "csv"}).content.decode("utf-8-sig")
    assert "'=cmd" in csv and "Verified success" in csv
    assert world.client(world.viewer_a).get(f"{base(world)}/custom-field-jobs/{body['id']}/report/").status_code == 404


def test_typed_values_are_validated(world, ready):
    from apps.customfields.definitions import ValueInvalid, normalise, same

    assert normalise("Number", " 42 ") == "42" and normalise("Boolean", "Yes") == "true"
    assert normalise("Date", "2026-12-31") == "2026-12-31" and same("Number", "42.0", "42")
    for ftype, bad in (
        ("Number", "4x"),
        ("Boolean", "maybe"),
        ("Date", "31/12/2026"),
        ("Text", ""),
        ("Text", "x" * 256),
    ):
        with pytest.raises(ValueInvalid):
            normalise(ftype, bad)
    cost = CustomFieldDefinition.objects.get(name="Cost Center")
    resp = world.client(world.engineer_a).post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(cost.id), "value": "abc", "assets": [str(workstations(world, 1)[0].asset_id)]},
        format="json",
    )
    assert resp.status_code == 400


def test_device_page_shows_editable_fields_with_current_values(world, ready):
    ws = workstations(world, 2)
    body = world.client(world.viewer_a).get(f"{base(world)}/custom-fields/device/{ws[1].asset_id}/").json()
    assert body["workstation"] is True
    values = {f["name"]: f["value"] for f in body["fields"]}
    assert values == {"PatchRing": "Ring 2", "Cost Center": None, "Encryption Exempt": None}


def test_select_all_matching_filters_becomes_a_fixed_list(world, ready):
    ws = workstations(world, 1)[0]
    eng = world.client(world.engineer_a)
    body = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 0", "filters": {"search": ws.hostname}},
        format="json",
    ).json()
    rows = items(world, eng, body["id"])
    assert [r["hostname"] for r in rows] == [ws.hostname] and body["source"] == "selection"
    # Later inventory changes do not alter the job's device list.
    assert AssignmentItem.objects.filter(job_id=body["id"]).count() == 1
    bad = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 0", "filters": {"offline_days": "9999"}},
        format="json",
    )
    assert bad.status_code == 400


def test_preview_expiry_is_shown_and_waiting_jobs_can_be_listed(world, ready, django_capture_on_commit_callbacks):
    eng = world.client(world.engineer_a)
    ws = workstations(world, 1)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 2", "assets": [str(ws[0].asset_id)]},
        format="json",
    ).json()
    assert job["preview_expires_at"] is None
    with django_capture_on_commit_callbacks(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    job = eng.get(f"{base(world)}/custom-field-jobs/{job['id']}/").json()
    assert job["state"] == "previewed" and job["preview_expires_at"] > job["previewed_at"]
    admin = world.client(world.admin_a)
    waiting = admin.get(f"{base(world)}/custom-field-jobs/", {"state": "previewed,awaiting_approval"}).json()
    assert [j["id"] for j in waiting["results"]] == [job["id"]]
    assert not admin.get(f"{base(world)}/custom-field-jobs/", {"state": "completed"}).json()["results"]


def test_administrator_applies_above_the_threshold_in_one_step(
    world, ready, settings, django_capture_on_commit_callbacks
):
    """Product owner 2026-11-24: one authorization. Without REQUIRE_SECOND_APPROVER the administrator's confirm is
    also the approval; it is audited as self_approved. An engineer's job still waits for an administrator."""
    from apps.audit.models import AuditEvent

    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    ready.custom_field_approval_threshold = 1
    ready.save()
    ws = workstations(world, 3)
    payload = {"field": str(ring(world).id), "value": "Ring 0", "assets": [str(o.asset_id) for o in ws[1:3]]}
    admin = world.client(world.admin_a)
    job = admin.post(f"{base(world)}/custom-field-jobs/", payload, format="json").json()
    with django_capture_on_commit_callbacks(execute=True):
        admin.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    with django_capture_on_commit_callbacks(execute=True):
        body = admin.post(
            f"{base(world)}/custom-field-jobs/{job['id']}/confirm/", {"confirm": True}, format="json"
        ).json()
    assert body["state"] in ("queued", "running", "completed")
    stored = AssignmentJob.objects.get(pk=job["id"])
    assert stored.state == "completed" and stored.approved_by_id == world.admin_a.id
    assert len(fixtures.FIXTURE_CUSTOM_FIELDS) == 2
    confirmed = AuditEvent.objects.filter(target_id=job["id"], action__endswith="confirmed").get()
    assert confirmed.metadata["self_approved"] is True and confirmed.metadata["approval_required"] is True


def _update_tbd_job(world, ready, capture):
    """A device holding the placeholder "TBD" is updated to "Ring 1" (live report 2026-11-27)."""
    ws = workstations(world, 1)[0]
    fixtures.FIXTURE_CUSTOM_FIELDS[(str(ready.id), "901", str(ws.asset.external_id))] = "TBD"
    eng = world.client(world.engineer_a)
    job = eng.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "Ring 1", "assets": [str(ws.asset_id)]},
        format="json",
    ).json()
    with capture(execute=True):
        eng.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    jobs.confirm(AssignmentJob.objects.get(pk=job["id"]), world.engineer_a, acknowledge_overwrite=True)
    return job, ws, eng


class _AnswersOkWithoutApplying:
    """HTTP 200 echoing the new value, but VSA X keeps the old one."""

    def __init__(self):
        self.calls = []

    def send(self, method, url, **kw):
        self.calls.append((method, url))
        body = kw["json"]
        return fixtures.FakeResponse(200, {"Data": {"ContextItemId": body["ContextItemId"], "Value": body["Value"]}})


def test_update_answered_ok_but_not_applied_is_reported_precisely(world, ready, django_capture_on_commit_callbacks):
    job, _ws, eng = _update_tbd_job(world, ready, django_capture_on_commit_callbacks)
    transport = _AnswersOkWithoutApplying()
    jobs.execute(job["id"], writer=VsaCustomFieldWriter(ready, transport=transport))
    assert [m for m, _ in transport.calls] == ["PUT"] and transport.calls[0][1].endswith("/updateAssigned")
    row = items(world, eng, job["id"])[0]
    assert (row["result"], row["error_code"], row["final_value"]) == (
        "verification_failed",
        "update_not_applied",
        "TBD",
    )
    event = AuditEvent.objects.filter(target_id=job["id"], action="custom_field.assignment").latest("created_at")
    expected = (
        "VSA X answered OK (HTTP 200, no content type, 0 bytes) and echoed the new value; "
        "reading the device back shows 'TBD'."
    )
    assert event.metadata["note"] == expected and row["action_note"] == expected


def test_update_answered_by_a_proxy_page_shows_the_answer_shape(world, ready, django_capture_on_commit_callbacks):
    job, _ws, eng = _update_tbd_job(world, ready, django_capture_on_commit_callbacks)

    class ProxyPage:
        def send(self, method, url, **kw):
            response = fixtures.FakeResponse(
                200, ValueError("not json"), {"Content-Type": "text/html", "Server": "BigIP"}
            )
            response.content = (
                b"<html><head><title>Request Rejected</title></head><body>" + b"x" * 940 + b"</body></html>"
            )
            return response

    jobs.execute(job["id"], writer=VsaCustomFieldWriter(ready, transport=ProxyPage()))
    row = items(world, eng, job["id"])[0]
    assert row["error_code"] == "update_not_applied"
    assert "VSA X answered OK (HTTP 200, text/html," in row["action_note"]
    assert "not the documented API answer); reading the device back shows 'TBD'." in row["action_note"]
    assert 'Answered by: page title "Request Rejected"; Server: BigIP.' in row["action_note"]


def test_update_that_shows_up_late_is_verified(world, ready, django_capture_on_commit_callbacks, monkeypatch):
    job, ws, eng = _update_tbd_job(world, ready, django_capture_on_commit_callbacks)
    key = (str(ready.id), "901", str(ws.asset.external_id))

    def slow_vsa(seconds):
        if seconds == jobs.LATE_READ_BACK_DELAY:
            fixtures.FIXTURE_CUSTOM_FIELDS[key] = "Ring 1"  # VSA X applies it only after the first read-backs

    monkeypatch.setattr(jobs, "sleep", slow_vsa)
    jobs.execute(job["id"], writer=VsaCustomFieldWriter(ready, transport=_AnswersOkWithoutApplying()))
    row = items(world, eng, job["id"])[0]
    assert (row["result"], row["final_value"]) == ("verified", "Ring 1")


def test_export_apply_script_has_no_token_keeps_tls_and_lists_unapplied_devices(
    world, ready, django_capture_on_commit_callbacks
):
    """CFA-12: an administrator exports a Python script to run from an allowlisted workstation (WAF case)."""
    job, ws, _eng = _update_tbd_job(world, ready, django_capture_on_commit_callbacks)
    jobs.execute(job["id"], writer=VsaCustomFieldWriter(ready, transport=_AnswersOkWithoutApplying()))
    resp = world.client(world.admin_a).get(f"{base(world)}/custom-field-jobs/{job['id']}/script/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/x-python; charset=utf-8"
    assert "attachment" in resp["Content-Disposition"] and resp["Content-Disposition"].endswith('.py"')
    body = resp.content.decode()
    # The unapplied device and its target value are in the script; the token never is.
    assert str(ws.asset.external_id) in body and '"value": "Ring 1"' in body
    # It asks for the token on the workstation (secret hidden), and still honours env vars; never from a server.
    assert "getpass.getpass(" in body and "input(" in body
    assert "VSA_TOKEN_ID" in body and "VSA_TOKEN_SECRET" in body
    assert "verify=True" in body and "verify=False" not in body
    # No hardcoded auth header or stored credential reference: the token comes only from the prompt / environment.
    assert "Authorization" not in body
    assert 'os.environ.get("VSA_TOKEN_SECRET"' in body
    assert (ready.credential_ref == "") or (ready.credential_ref not in body)
    # Audit recorded with a device count, no values.
    event = AuditEvent.objects.filter(target_id=job["id"], action="custom_field.script_exported").latest("created_at")
    assert event.metadata["devices"] == 1 and "Ring 1" not in str(event.metadata)


def test_export_apply_script_requires_apply_permission(world, ready, django_capture_on_commit_callbacks):
    job, _ws, eng = _update_tbd_job(world, ready, django_capture_on_commit_callbacks)
    # An engineer (prepare/preview only) may not export a runnable writer.
    assert eng.get(f"{base(world)}/custom-field-jobs/{job['id']}/script/").status_code in (403, 404)
    # Another customer's user cannot reach this job at all.
    assert world.client(world.engineer_b).get(f"{base(world)}/custom-field-jobs/{job['id']}/script/").status_code in (
        403,
        404,
    )
