"""Reference versions from a pasted VSA 10 Application Catalog table: only installed programs, reviewed as usual."""

from __future__ import annotations

import pytest

from apps.software.models import CatalogRevision
from apps.software.vsa_catalog import CATALOG_URL, display_name, key, parse

from .test_p1_api import reviewer, synced  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/catalog/imports/from-vsa-catalog/"
TABLE = "\n".join(
    [
        "Application\tVendor\tTier\tVersion\tRelease Date",
        "7-zip (64-bit)\tIgor Pavlov\t2\t26.06\t2026-11-09",
        "Google Chrome (32-bit)\tGoogle LLC\t1\t131.0.6778.86\t2026-11-05",
        "Google Chrome (64-bit)\tGoogle LLC\t1\t131.0.6778.86\t2026-11-05",
        "Contoso Tool x64\tContoso\t3\t2.0\t2026-10-01",
        "Contoso Tool x86\tContoso\t3\t1.5\t2025-01-01",
        "Old Viewer (discontinued)\tOld Co\t3\t1.0\t2020-01-01",
        "Odd App\tOdd Co\t3\tbuild-7\t2026-01-01",
    ]
)


@pytest.mark.parametrize(
    ("catalog", "installed"),
    [
        ("7-zip (64-bit)", "7-Zip 26.00 (x64)"),
        ("Mozilla Firefox (64-bit)", "Mozilla Firefox (x64 en-US)"),
        ("Amazon Corretto 11 x64", "Amazon Corretto 11"),
        ("Adobe Acrobat Reader DC (64-bit)", "Adobe Acrobat Reader DC"),
    ],
)
def test_catalog_and_installed_names_meet_after_normalising(catalog, installed):
    assert key(catalog) == key(installed)


def test_other_products_do_not_match():
    assert key("Google Chrome") != key("Google Chrome Remote Desktop")
    assert display_name("7-zip (64-bit)") == "7-zip" and display_name("Amazon Corretto 8 x86") == "Amazon Corretto 8"


def test_parses_tab_csv_and_pipe_tables_and_skips_unusable_rows():
    entries, skipped = parse(TABLE)
    assert [e["application"] for e in entries][:3] == [
        "7-zip (64-bit)",
        "Google Chrome (32-bit)",
        "Google Chrome (64-bit)",
    ]
    assert {s["application"] for s in skipped} == {"Old Viewer (discontinued)", "Odd App"}
    csv_entries, _ = parse(
        'Application,Vendor,Tier,Version\n"Adobe Acrobat Pro/Standard (64-bit)","Adobe Inc.",2,26.003.22075'
    )
    assert csv_entries[0]["version"] == "26.003.22075"
    pipe, _ = parse(
        "| Application | Vendor | Tier | Version | Release Date |\n"
        "|---|---|---|---|---|\n"
        "| AnyDesk | AnyDesk | 3 | 9.8.3 | 2026-10-27 |"
    )
    assert pipe[0]["application"] == "AnyDesk"


def test_only_installed_programs_become_reviewed_reference_versions(
    world,
    synced,  # noqa: F811
    reviewer,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    admin = world.client(world.super_admin)
    body = admin.post(URL, {"text": TABLE}, format="json").json()
    assert body["stats"] == {
        "catalog_entries": 5,
        "matched_programs": 1,
        "already_current": 0,
        "not_installed": 1,
        "skipped": 3,
    }
    (row,) = body["rows"]
    assert (row["vendor"], row["product"], row["reference_version"]) == ("Google LLC", "Google Chrome", "131.0.6778.86")
    assert row["vendor_url"] == CATALOG_URL and row["source_type"] == "vsa_application_catalog"
    assert row["aliases"] == [
        {"name_pattern": "Google Chrome", "publisher_pattern": "Google LLC", "match_type": "exact"}
    ]
    (match,) = body["matched"]
    assert match["catalog_names"] == ["Google Chrome (32-bit)", "Google Chrome (64-bit)"]
    assert match["older"] > 0 and match["newer"] == 0 and not match["warnings"]
    assert any("versions differ" in s["reason"] for s in body["skipped"])  # Contoso 32/64-bit disagree
    assert body["valid"] and body["preview"][0]["change"] == "new_product"
    assert CatalogRevision.objects.count() == 0  # a dry run

    # Submitted and approved through the ordinary review: Chrome is now compared and outdated installs are flagged.
    created = admin.post("/api/v1/catalog/imports/", {"rows": body["rows"]}, format="json")
    assert created.status_code == 201, created.content
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            world.client(reviewer).post(f"/api/v1/catalog/imports/{created.json()['id']}/approve/").status_code == 200
        )
    summary = world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()
    chrome = next(p for p in summary["products"] if "Chrome" in p["label"])
    assert chrome["states"]["outdated"] == 3

    again = admin.post(URL, {"text": TABLE}, format="json").json()
    assert again["stats"]["already_current"] == 1 and again["rows"] == []


def test_version_format_mismatch_is_flagged(world, synced):  # noqa: F811
    body = (
        world.client(world.super_admin)
        .post(URL, {"text": "Google Chrome\tGoogle LLC\t1\t13.0\t2026-11-05"}, format="json")
        .json()
    )
    assert "HIGHER version" in body["matched"][0]["warnings"][0]


def test_catalog_paste_is_system_admin_only(world, synced):  # noqa: F811
    for user in (world.admin_a, world.engineer_a, world.viewer_a):
        assert world.client(user).post(URL, {"text": TABLE}, format="json").status_code == 403
    assert world.client(world.super_admin).post(URL, {"text": "nothing useful"}, format="json").status_code == 400
