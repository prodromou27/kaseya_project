"""VSA2-01..04 onboarding reconciliation: importer security, deterministic matching, gating, review, exports.

Fixture data only (synthetic devices synced through the fixture VSA transport) — NOT live validation.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.audit.models import AuditEvent
from apps.integrations.models import DatasetGeneration
from apps.onboarding import importer, matching, services
from apps.onboarding.matching import Device, Params, reconcile
from apps.onboarding.models import ExpectedInventoryUpload, ReconciliationResult, ReconciliationRun

from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _storage(settings, tmp_path):
    settings.ONBOARDING_STORAGE_DIR = tmp_path / "onboarding"


def csv_bytes(rows: list[list[str]], delimiter: str = ",") -> bytes:
    buf = io.StringIO()
    csv.writer(buf, delimiter=delimiter).writerows(rows)
    return buf.getvalue().encode("utf-8")


def xlsx_bytes(rows: list[list[object]], *, extra_sheet: bool = False) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Expected"
    for r in rows:
        ws.append(r)
    if extra_sheet:
        wb.create_sheet("Other").append(["x"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def patch_zip(data: bytes, add: dict[str, bytes] | None = None, replace: dict[str, bytes] | None = None) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info.filename, (replace or {}).get(info.filename, src.read(info.filename)))
        for name, content in (add or {}).items():
            dst.writestr(name, content)
    return out.getvalue()


# ================================================================ VSA2-01 importer


def test_csv_parsing_delimiters_encodings_and_mapping_suggestion():
    rows = [["Computer Name", "Serial No", "MAC Address", "Site"], ["PC1", "SN1", "00-11-22-33-44-55", "HQ"]]
    for data in (csv_bytes(rows), csv_bytes(rows, ";"), "\n".join(";".join(r) for r in rows).encode("utf-16")):
        wb = importer.parse("inventory.CSV", data)
        ws = wb.sheet("CSV")
        headers = importer.headers_for(ws, 1)
        assert headers == rows[0]
        assert importer.suggest_mapping(headers) == {"hostname": 0, "serial_number": 1, "mac": 2, "expected_site": 3}
    with pytest.raises(importer.ImportRejected) as exc:
        importer.parse("x.csv", "Computer;Name\nPC\xe9;1".encode("latin-1"))
    assert exc.value.code == "encoding_not_supported"


def test_xlsx_formulas_are_never_evaluated_and_unicode_is_kept():
    data = xlsx_bytes([["Hostname", "Serial"], ["ΠΕΛΑΤΗΣ-01", '=CONCATENATE("SN","1")'], [12345.0, "SN2"]])
    ws = importer.parse("expected.xlsx", data).sheet("Expected")
    assert ws.formula_cells == 1
    rows = importer.mapped_rows(ws, 1, {"hostname": 0, "serial_number": 1})
    assert rows == [
        (2, {"hostname": "ΠΕΛΑΤΗΣ-01", "serial_number": ""}),
        (3, {"hostname": "12345", "serial_number": "SN2"}),
    ]


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("book.xlsm", b"PK\x03\x04", "unsupported_file_type"),
        ("book.xls", b"\xd0\xcf\x11\xe0", "unsupported_file_type"),
        ("run.exe", b"MZ", "unsupported_file_type"),
        ("book.xlsx", b"Hostname\nPC1\n", "content_mismatch"),
        ("list.csv", b"PK\x03\x04rest", "content_mismatch"),
        ("list.csv", b"", "empty_file"),
    ],
)
def test_rejected_types_and_magic_bytes(name, data, code):
    with pytest.raises(importer.ImportRejected) as exc:
        importer.parse(name, data)
    assert exc.value.code == code


def test_active_content_external_links_and_dtd_are_rejected():
    base = xlsx_bytes([["Hostname"], ["PC1"]])
    for add in (
        {"xl/vbaProject.bin": b"x"},
        {"xl/externalLinks/externalLink1.xml": b"<x/>"},
        {"xl/embeddings/o.bin": b"x"},
    ):
        with pytest.raises(importer.ImportRejected) as exc:
            importer.parse("b.xlsx", patch_zip(base, add=add))
        assert exc.value.code == "active_content"
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><sst xmlns="x"><si><t>&a;</t></si></sst>'
    with pytest.raises(importer.ImportRejected) as exc:
        importer.parse("b.xlsx", patch_zip(base, add={"xl/sharedStrings2.xml": evil}))
    assert exc.value.code == "active_content"


def test_zip_bomb_and_size_limits(settings):
    base = xlsx_bytes([["Hostname"], ["PC1"]])
    bomb = patch_zip(base, add={"xl/media/pad.bin": b"\0" * (8 * 1024 * 1024)})
    with pytest.raises(importer.ImportRejected) as exc:
        importer.parse("b.xlsx", bomb)
    assert exc.value.code == "workbook_too_large"
    settings.ONBOARDING_MAX_UPLOAD_BYTES = 100
    with pytest.raises(importer.ImportRejected) as exc:
        importer.parse("b.csv", b"Hostname\n" + b"PC1\n" * 50)
    assert exc.value.code == "file_too_large"


def test_row_and_column_limits(settings):
    settings.ONBOARDING_MAX_ROWS = 5
    with pytest.raises(importer.ImportRejected) as exc:
        importer.parse("b.csv", csv_bytes([["Hostname"]] + [[f"PC{i}"] for i in range(80)]))
    assert exc.value.code == "too_many_rows"
    with pytest.raises(importer.ImportRejected) as exc:
        importer.parse("b.csv", csv_bytes([[f"c{i}" for i in range(70)]]))
    assert exc.value.code == "too_many_columns"


def test_mapping_validation():
    with pytest.raises(importer.ImportRejected, match="invalid_mapping"):
        importer.validate_mapping({"department": 0}, 3)  # no identifier column
    with pytest.raises(importer.ImportRejected):
        importer.validate_mapping({"hostname": 0, "serial_number": 0}, 3)  # same column twice
    with pytest.raises(importer.ImportRejected):
        importer.validate_mapping({"hostname": 9}, 3)
    with pytest.raises(importer.ImportRejected):
        importer.validate_mapping({"password": 0}, 3)
    assert importer.validate_mapping({"hostname": 1, "notes": None}, 3) == {"hostname": 1}


# ================================================================ VSA2-02 matching engine


def dev(n: int, **kw) -> Device:
    base = {
        "asset_id": f"a{n}",
        "external_id": f"guid-{n}",
        "hostname": f"PC{n:03d}",
        "domain": "corp.example",
        "serial": f"SN{n:04d}",
        "org_id": "11",
        "org_name": "Org A",
        "site_id": "5",
        "site_name": "HQ",
        "group_id": "51",
        "group_name": "Workstations",
        "last_seen_online": NOW - timedelta(hours=1),
        "is_agent_installed": True,
        "network_status": "collected",
    }
    base.update(kw)
    return Device(**base)


def row(n: int, **values: str) -> tuple[int, dict[str, str]]:
    return n, values


def test_hundred_row_fixture_classifies_exactly():
    """Acceptance: 80 exact, 10 not found, 5 wrong group, 3 ambiguous, 2 duplicates; totals consistent."""
    devices = [dev(i) for i in range(1, 89)]
    for k, name in enumerate(("DUPA", "DUPB", "DUPC")):  # same hostname in two sites
        devices.append(dev(200 + 2 * k, hostname=name, serial="", site_id="5", site_name="HQ"))
        devices.append(dev(201 + 2 * k, hostname=name, serial="", site_id="6", site_name="Branch"))
    rows = [row(i + 1, hostname=f"PC{i:03d}", expected_site="HQ", expected_group="Workstations") for i in range(1, 81)]
    rows += [row(100 + i, hostname=f"PC{i:03d}", expected_site="HQ", expected_group="Servers") for i in range(81, 86)]
    rows += [row(200 + i, hostname=f"MISSING{i:02d}") for i in range(10)]
    rows += [row(300 + k, hostname=name) for k, name in enumerate(("DUPA", "DUPB", "DUPC"))]
    rows += [row(400, hostname="PC001", expected_site="HQ"), row(401, hostname="pc002", expected_site="hq")]
    assert len(rows) == 100
    out = reconcile(rows, devices, Params(snapshot_at=NOW))
    s = out.summary
    assert s["classifications"] == {
        "AMBIGUOUS": 3,
        "DUPLICATE_INPUT": 2,
        "MATCHED_CORRECT": 80,
        "MATCHED_WRONG_GROUP": 5,
        "NOT_FOUND_IN_COMPLETE_SNAPSHOT": 10,
    }
    assert sum(s["classifications"].values()) == s["expected_rows"] == 100
    # 94 devices: 85 matched, PC086-088 unexpected, six ambiguous candidates pending review.
    assert s["snapshot_devices"] == 94 and s["matched_devices"] == 85
    assert s["unexpected_vsa_assets"] == 3 and s["unexpected_pending_review"] == 6
    assert s["matched_devices"] + s["unexpected_vsa_assets"] + s["unexpected_pending_review"] == s["snapshot_devices"]
    dup = next(r for r in out.rows if r.row_number == 400)
    assert dup.evidence["duplicate_of_row"] == 2
    nf = next(r for r in out.rows if r.classification == "NOT_FOUND_IN_COMPLETE_SNAPSHOT")
    assert "does not prove the agent is not installed" in nf.evidence["note"]


def test_precedence_serial_beats_hostname_and_conflicts_are_ambiguous():
    devices = [dev(1), dev(2, hostname="RENAMED")]
    out = reconcile([row(2, serial_number="sn0002", hostname="RENAMED")], devices, Params(snapshot_at=NOW))
    assert out.rows[0].classification == "MATCHED_CORRECT" and out.rows[0].evidence["basis"] == "serial_number"
    out = reconcile([row(2, serial_number="SN0001", hostname="RENAMED")], devices, Params(snapshot_at=NOW))
    assert out.rows[0].classification == "AMBIGUOUS"
    assert {d.asset_id for d in out.rows[0].candidates} == {"a1", "a2"}
    out = reconcile([row(2, source_device_id="{GUID-2}", hostname="whatever")], devices, Params(snapshot_at=NOW))
    assert out.rows[0].device.asset_id == "a2" and out.rows[0].evidence["basis"] == "source_device_id"


def test_placeholder_and_non_unique_serials_fall_through():
    devices = [dev(1, serial="To be filled by O.E.M."), dev(2, serial="DUP"), dev(3, serial="DUP")]
    out = reconcile(
        [
            row(2, serial_number="To Be Filled By O.E.M.", hostname="PC001"),
            row(3, serial_number="DUP", hostname="PC003"),
        ],
        devices,
        Params(snapshot_at=NOW),
    )
    assert [r.device.asset_id for r in out.rows] == ["a1", "a3"]
    assert out.rows[0].evidence["input_problems"]["serial_number"].startswith("placeholder")
    assert out.rows[1].evidence["steps"][0]["note"].startswith("serial number is not unique")


def test_fqdn_and_hostname_with_domain():
    devices = [dev(1), dev(2, hostname="PC001", domain="other.example", site_id="6", site_name="Branch")]
    out = reconcile([row(2, hostname="pc001.corp.example")], devices, Params(snapshot_at=NOW))
    assert out.rows[0].device.asset_id == "a1" and out.rows[0].evidence["basis"] == "fqdn"
    out = reconcile([row(2, hostname="PC001", expected_site="Branch")], devices, Params(snapshot_at=NOW))
    assert out.rows[0].device.asset_id == "a2"  # narrowed by expected site
    assert out.rows[0].evidence["steps"][0] == {
        "identifier": "hostname",
        "candidates": 2,
        "after_expected_placement": 1,
    }


def test_ip_never_auto_confirms_and_mac_only_requires_review():
    devices = [dev(1, macs=frozenset({"00AA00000001", "0A0000000001"}), ips=frozenset({"10.0.0.5"}))]
    p = Params(snapshot_at=NOW)
    assert reconcile([row(2, ip_address="10.0.0.5")], devices, p).rows[0].classification == "AMBIGUOUS"
    out = reconcile([row(2, hostname="NOPE", ip_address="10.0.0.5")], devices, p)
    assert out.rows[0].classification == "NOT_FOUND_IN_COMPLETE_SNAPSHOT"
    out = reconcile([row(2, mac="00:aa:00:00:00:01")], devices, p)
    assert out.rows[0].classification == "AMBIGUOUS" and out.rows[0].evidence["reason"].startswith("MAC-only")
    out = reconcile([row(2, mac="0A-00-00-00-00-01")], devices, p)  # locally administered (virtual/cloned)
    assert out.rows[0].classification == "NOT_FOUND_IN_COMPLETE_SNAPSHOT"


def test_multi_nic_device_counts_once_and_any_nic_corroborates():
    devices = [dev(1, macs=frozenset({"00AA00000001", "00AA00000002"}))]
    out = reconcile([row(2, hostname="PC001", mac="00AA00000002")], devices, Params(snapshot_at=NOW))
    assert out.rows[0].evidence["mac_check"] == "corroborated"
    assert out.summary["snapshot_devices"] == 1 and out.summary["unexpected_vsa_assets"] == 0


def test_wrong_site_wrong_org_and_unknown_group():
    devices = [dev(1), dev(2, group_id="", group_name="")]
    p = Params(snapshot_at=NOW)
    assert reconcile([row(2, hostname="PC001", expected_site="Branch")], devices, p).rows[0].classification == (
        "MATCHED_WRONG_SITE"
    )
    assert reconcile([row(2, hostname="PC001", expected_organization="Org B")], devices, p).rows[0].classification == (
        "REVIEW_WRONG_ORGANIZATION"
    )
    r = reconcile([row(2, hostname="PC002", expected_group="Workstations")], devices, p).rows[0]
    assert r.classification == "MATCHED_WRONG_GROUP" and r.evidence["group_note"].startswith("device is not in any")
    r = reconcile([row(2, hostname="PC001", expected_organization="11", expected_site="5")], devices, p).rows[0]
    assert r.classification == "MATCHED_CORRECT" and r.evidence["placement_not_specified"] == ["group"]


def test_invalid_and_duplicate_inputs():
    devices = [dev(1)]
    out = reconcile(
        [
            row(2, department="Finance"),
            row(3, mac="not-a-mac"),
            row(4, asset_tag="AT-1"),
            row(5, serial_number="SN0001"),
            row(6, hostname="PC001"),  # different identifier, same matched device
        ],
        devices,
        Params(snapshot_at=NOW),
    )
    cls = [r.classification for r in out.rows]
    assert cls == ["INVALID_INPUT", "INVALID_INPUT", "INVALID_INPUT", "MATCHED_CORRECT", "DUPLICATE_INPUT"]
    assert out.rows[1].evidence["input_problems"] == {"mac": "malformed MAC address"}
    assert out.rows[2].evidence["asset_tag"].startswith("not reported by VSA X")
    assert out.rows[4].evidence["duplicate_of_row"] == 5


def test_secondary_flags_keep_offline_devices_onboarded():
    devices = [
        dev(1, last_seen_online=NOW - timedelta(days=3)),
        dev(2, last_seen_online=None, network_status="not_collected"),
        dev(3),
    ]
    out = reconcile(
        [row(2, hostname="PC001"), row(3, hostname="PC002"), row(4, hostname="PC003")],
        devices,
        Params(snapshot_at=NOW, stale_source=True),
    )
    assert [r.classification for r in out.rows] == ["MATCHED_CORRECT"] * 3
    assert out.rows[0].flags == ["OFFLINE", "STALE_SOURCE"]
    assert out.rows[1].flags == ["OFFLINE", "STALE_AGENT", "STALE_SOURCE", "MISSING_NETWORK_DATA"]
    assert "OLD_AGENT" in out.summary["parameters"]["flags_not_evaluated"]


# ================================================================ VSA2-03 API, gating and isolation

URL = "/api/v1/customers/{c}/onboarding/"


@pytest.fixture
def synced(world, env):  # noqa: F811
    a = [
        asset(1, 11, ip="10.0.1.10", hostname="SHARED-NAME"),
        asset(2, 11, ip="10.0.1.11"),
        asset(3, 11, ip="10.0.1.12", group=52),
        asset(4, 11, site=6, group=61),
    ]
    b = [asset(1, 22, ip="10.0.1.10", hostname="SHARED-NAME", site=8, group=81)]
    run(
        env["ma"], world.engineer_a, __import__("apps.integrations.vsa.fixtures", fromlist=["x"]).FixtureVsaTransport(a)
    )
    run(
        env["mb"], world.engineer_b, __import__("apps.integrations.vsa.fixtures", fromlist=["x"]).FixtureVsaTransport(b)
    )
    DatasetGeneration.objects.filter(is_current=True).update(published_at=timezone.now())
    return env


def upload(client, customer, rows, name="expected.csv"):
    data = csv_bytes(rows) if name.endswith(".csv") else xlsx_bytes(rows)
    f = io.BytesIO(data)
    f.name = name
    return client.post(URL.format(c=customer.id) + "uploads/", {"file": f}, format="multipart")


def start(client, customer, upload_id, mapping, cb, **extra):
    with cb(execute=True):
        return client.post(
            URL.format(c=customer.id) + "runs/",
            {"upload": upload_id, "sheet": "CSV", "header_row": 1, "mapping": mapping, **extra},
            format="json",
        )


EXPECTED = [
    ["Hostname", "Serial", "Site", "Group", "Notes"],
    ["SHARED-NAME", "", "5", "G51", '=HYPERLINK("http://x")'],
    ["PC2", "", "5", "G52", ""],
    ["PC3", "", "5", "G52", ""],
    ["GHOST-01", "", "", "", ""],
    ["PC2", "", "5", "G52", "dup"],
]
MAP = {"hostname": 0, "serial_number": 1, "expected_site": 2, "expected_group": 3, "notes": 4}


def test_full_flow_preview_run_results_export(world, synced, django_capture_on_commit_callbacks):
    c = world.client(world.engineer_a)
    resp = upload(c, world.customer_a, EXPECTED)
    assert resp.status_code == 201, resp.content
    up = resp.json()
    assert up["sheets"][0]["rows"] == 6 and up["available"]
    prev = c.post(URL.format(c=world.customer_a.id) + f"uploads/{up['id']}/preview/", {"sheet": "CSV"}, format="json")
    assert prev.status_code == 200
    assert prev.json()["suggested_mapping"] == {
        "hostname": 0,
        "serial_number": 1,
        "expected_site": 2,
        "expected_group": 3,
        "notes": 4,
    }
    assert prev.json()["data_rows"] == 5

    r = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks)
    assert r.status_code == 202, r.content
    run_obj = ReconciliationRun.objects.get(pk=r.json()["id"])
    assert run_obj.state == "completed", run_obj.error_code
    s = run_obj.summary
    assert s["classifications"] == {
        "DUPLICATE_INPUT": 1,
        "MATCHED_CORRECT": 2,
        "MATCHED_WRONG_GROUP": 1,
        "NOT_FOUND_IN_COMPLETE_SNAPSHOT": 1,
    }
    assert s["unexpected_vsa_assets"] == 1  # PC4 (site 6) not in the expected list
    # Customer B's SHARED-NAME device is never a candidate: the match is A's device in org 11.
    shared = ReconciliationResult.objects.get(run=run_obj, row_number=2)
    assert shared.actual["organization_id"] == "11" and shared.asset.customer_id == world.customer_a.id

    res = c.get(URL.format(c=world.customer_a.id) + f"runs/{run_obj.id}/results/?classification=MATCHED_WRONG_GROUP")
    assert res.status_code == 200 and [x["row_number"] for x in res.json()["results"]] == [3]
    unexp = c.get(URL.format(c=world.customer_a.id) + f"runs/{run_obj.id}/results/?kind=unexpected").json()
    assert [x["actual"]["hostname"] for x in unexp["results"]] == ["PC4"]

    x = c.get(URL.format(c=world.customer_a.id) + f"runs/{run_obj.id}/export/?output=xlsx")
    assert x.status_code == 200 and x["Cache-Control"] == "no-store"
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == [
        "Summary",
        "All Expected",
        "Matched Correct",
        "Wrong Group",
        "Wrong Site",
        "Not Found",
        "Ambiguous",
        "Duplicate-Invalid",
        "Unexpected VSA",
        "Recommendations",
    ]
    data_rows = {name: wb[name].max_row - 1 for name in wb.sheetnames[1:9]}
    assert data_rows["All Expected"] == 5
    assert sum(data_rows[n] for n in wb.sheetnames[2:8]) == data_rows["All Expected"]
    assert data_rows["Unexpected VSA"] == 1
    notes_col = list(next(wb["All Expected"].iter_rows(max_row=1, values_only=True))).index("Notes")
    cell = next(wb["All Expected"].iter_rows(min_row=2, max_row=2))[notes_col]
    assert cell.data_type == "s" and cell.value.startswith("'=")  # formula injection neutralised
    csv_resp = c.get(URL.format(c=world.customer_a.id) + f"runs/{run_obj.id}/export/?output=csv")
    assert b"'=HYPERLINK" in csv_resp.content and b"\n=HYPERLINK" not in csv_resp.content
    assert AuditEvent.objects.filter(action="onboarding.exported", customer=world.customer_a).count() == 2


def test_cross_customer_isolation(world, synced, django_capture_on_commit_callbacks):
    a = world.client(world.engineer_a)
    up = upload(a, world.customer_a, EXPECTED).json()
    b = world.client(world.engineer_b)
    assert b.get(URL.format(c=world.customer_a.id) + "uploads/").status_code == 404
    assert b.get(URL.format(c=world.customer_b.id) + f"uploads/{up['id']}/").status_code == 404
    r = start(b, world.customer_b, up["id"], MAP, django_capture_on_commit_callbacks)
    assert r.status_code == 400 and "upload" in r.json()["error"]["details"]
    gen_b = DatasetGeneration.objects.get(customer=world.customer_b, is_current=True)
    r = start(a, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks, generation=str(gen_b.id))
    assert r.status_code == 409 and r.json()["error"]["code"] == "generation_not_current"
    done = start(a, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks).json()
    assert b.get(URL.format(c=world.customer_b.id) + f"runs/{done['id']}/").status_code == 404
    assert b.get(URL.format(c=world.customer_b.id) + f"runs/{done['id']}/export/").status_code == 404
    assert not ReconciliationResult.objects.filter(customer=world.customer_a, asset__customer=world.customer_b).exists()


def test_role_capabilities(world, synced, django_capture_on_commit_callbacks):
    viewer = world.client(world.viewer_a)
    assert upload(viewer, world.customer_a, EXPECTED).status_code == 404  # needs customer.sync
    eng = world.client(world.engineer_a)
    up = upload(eng, world.customer_a, EXPECTED).json()
    done = start(eng, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks).json()
    assert viewer.get(URL.format(c=world.customer_a.id) + f"runs/{done['id']}/").status_code == 200
    assert viewer.get(URL.format(c=world.customer_a.id) + f"runs/{done['id']}/export/").status_code == 404
    assert world.client(world.outsider).get(URL.format(c=world.customer_a.id) + "runs/").status_code == 404
    assert world.client(None).get(URL.format(c=world.customer_a.id) + "runs/").status_code in (401, 403)


def test_incomplete_stale_and_missing_generation_are_blocked(world, synced, django_capture_on_commit_callbacks):
    c = world.client(world.engineer_a)
    up = upload(c, world.customer_a, EXPECTED).json()
    gen = DatasetGeneration.objects.get(customer=world.customer_a, is_current=True)
    gen.hierarchy_status = "failed"
    gen.save(update_fields=["hierarchy_status"])
    r = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks)
    assert r.status_code == 409 and r.json()["error"]["code"] == "hierarchy_incomplete"
    assert (
        c.get(URL.format(c=world.customer_a.id) + "runs/eligibility/").json()["blocked"]["code"]
        == "hierarchy_incomplete"
    )

    gen.hierarchy_status = "collected"
    gen.published_at = timezone.now() - timedelta(days=3)
    gen.save(update_fields=["hierarchy_status", "published_at"])
    r = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks)
    assert r.status_code == 409 and r.json()["error"]["code"] == "generation_stale"
    r = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks, allow_stale=True)
    assert r.status_code == 202
    res = ReconciliationResult.objects.filter(run_id=r.json()["id"], classification="MATCHED_CORRECT")
    assert res.exists() and all("STALE_SOURCE" in x.flags for x in res)

    DatasetGeneration.objects.filter(customer=world.customer_a).update(is_current=False, state="superseded")
    r = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_complete_generation"
    assert AuditEvent.objects.filter(action="onboarding.run_blocked", customer=world.customer_a).count() == 3


def test_pinned_generation_history_is_not_rewritten_by_new_sync(world, synced, django_capture_on_commit_callbacks):
    c = world.client(world.engineer_a)
    up = upload(c, world.customer_a, EXPECTED).json()
    first = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks).json()
    from apps.integrations.vsa.fixtures import FixtureVsaTransport

    run(synced["ma"], world.engineer_a, FixtureVsaTransport([asset(1, 11, ip="10.0.1.10", hostname="SHARED-NAME")]))
    DatasetGeneration.objects.filter(is_current=True).update(published_at=timezone.now())
    second = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks).json()
    r1, r2 = ReconciliationRun.objects.get(pk=first["id"]), ReconciliationRun.objects.get(pk=second["id"])
    assert r1.generation_id != r2.generation_id and r1.upload_sha256 == r2.upload_sha256
    assert r1.summary["classifications"]["MATCHED_CORRECT"] == 2
    assert r2.summary["classifications"]["NOT_FOUND_IN_COMPLETE_SNAPSHOT"] == 3
    r1.refresh_from_db()
    assert r1.summary["classifications"]["MATCHED_CORRECT"] == 2  # history unchanged


def test_review_of_ambiguous_row(world, synced, django_capture_on_commit_callbacks):
    c = world.client(world.engineer_a)
    up = upload(c, world.customer_a, [["IP"], ["10.0.1.11"]]).json()
    done = start(c, world.customer_a, up["id"], {"ip_address": 0}, django_capture_on_commit_callbacks).json()
    base = URL.format(c=world.customer_a.id) + f"runs/{done['id']}/results/"
    item = c.get(base + "?review_state=pending").json()["results"][0]
    assert item["classification"] == "AMBIGUOUS" and len(item["candidates"]) == 1
    cand = item["candidates"][0]["asset_id"]
    bad = c.post(
        base + f"{item['id']}/review/", {"decision": "match", "asset": str(world.customer_a.id)}, format="json"
    )
    assert bad.status_code == 400
    assert (
        world.client(world.viewer_a)
        .post(base + f"{item['id']}/review/", {"decision": "no_match"}, format="json")
        .status_code
        == 404
    )
    ok = c.post(
        base + f"{item['id']}/review/", {"decision": "match", "asset": cand, "note": "confirmed on site"}, format="json"
    )
    assert ok.status_code == 200, ok.content
    body = ok.json()
    assert body["classification"] == "AMBIGUOUS"  # engine result preserved
    assert body["reviewed_classification"] == "MATCHED_CORRECT" and body["reviewed_by"] == world.engineer_a.email
    again = c.post(base + f"{item['id']}/review/", {"decision": "no_match"}, format="json")
    assert again.status_code == 400


def test_db_enforces_customer_consistency_and_immutability(world, synced, django_capture_on_commit_callbacks):
    c = world.client(world.engineer_a)
    up = upload(c, world.customer_a, EXPECTED).json()
    done = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks).json()
    res = ReconciliationResult.objects.filter(run_id=done["id"]).first()
    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        ReconciliationResult.objects.filter(pk=res.pk).update(classification="MATCHED_CORRECT", evidence={"x": 1})
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        ReconciliationResult.objects.filter(pk=res.pk).update(customer=world.customer_b)
    other_asset = (
        __import__("apps.inventory.models", fromlist=["Asset"]).Asset.objects.filter(customer=world.customer_b).first()
    )
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        ReconciliationResult.objects.filter(pk=res.pk).update(reviewed_asset=other_asset)


def test_upload_retention_and_rejection_audit(world, synced, django_capture_on_commit_callbacks):
    c = world.client(world.engineer_a)
    bad = upload(c, world.customer_a, [["x"]], name="macro.xlsm")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unsupported_file_type"
    assert AuditEvent.objects.filter(action="onboarding.upload", outcome="denied").exists()
    up = upload(c, world.customer_a, EXPECTED).json()
    obj = ExpectedInventoryUpload.objects.get(pk=up["id"])
    path = services._storage_path(obj.storage_key)
    assert path.is_file()
    ExpectedInventoryUpload.objects.filter(pk=obj.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert services.purge_expired_uploads() == 1
    assert not path.exists()
    r = start(c, world.customer_a, up["id"], MAP, django_capture_on_commit_callbacks)
    assert r.status_code == 400 and r.json()["error"]["code"] == "upload_expired"
    up2 = upload(c, world.customer_a, EXPECTED).json()
    assert c.delete(URL.format(c=world.customer_a.id) + f"uploads/{up2['id']}/").status_code == 204
    assert ExpectedInventoryUpload.objects.get(pk=up2["id"]).purged_at is not None


def test_mapping_templates_are_customer_scoped(world, synced):
    a = world.client(world.engineer_a)
    url = URL.format(c=world.customer_a.id) + "templates/"
    r = a.post(url, {"name": "Acme layout", "header_row": 1, "columns": {"hostname": "Computer Name"}}, format="json")
    assert r.status_code == 201
    assert a.post(url, {"name": "Bad", "columns": {"password": "x"}}, format="json").status_code == 400
    assert world.client(world.engineer_b).get(url).status_code == 404
    assert world.client(world.engineer_b).get(URL.format(c=world.customer_b.id) + "templates/").json() == []


def test_xlsx_upload_with_sheet_selection(world, synced, django_capture_on_commit_callbacks):
    c = world.client(world.engineer_a)
    up = upload(c, world.customer_a, [["Device Name"], ["PC2"]], name="expected.xlsx").json()
    assert [s["name"] for s in up["sheets"]] == ["Expected"]
    with django_capture_on_commit_callbacks(execute=True):
        r = c.post(
            URL.format(c=world.customer_a.id) + "runs/",
            {"upload": up["id"], "sheet": "Expected", "mapping": {"hostname": 0}},
            format="json",
        )
    assert r.status_code == 202
    assert ReconciliationRun.objects.get(pk=r.json()["id"]).summary["classifications"] == {"MATCHED_CORRECT": 1}
    r = c.post(
        URL.format(c=world.customer_a.id) + "runs/",
        {"upload": up["id"], "sheet": "Nope", "mapping": {"hostname": 0}},
        format="json",
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_sheet"


def test_engine_version_recorded():
    assert matching.LOGIC_VERSION == "onboarding-match-1"
