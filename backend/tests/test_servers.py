"""SRV-01: servers and owner groups (portal-only), patching needs per server, report per owner. Fixture data."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.inventory.queries import current_observations
from apps.servers.models import ServerOwnerGroup

from .test_automation import demo  # noqa: F401
from .test_frozen_reports import request, rows_of

pytestmark = pytest.mark.django_db


def url(world, tail=""):
    return f"/api/v1/customers/{world.customer_a.id}/{tail}"


def make_group(world, name="Finance servers", email="finance.it@example.test"):
    resp = world.client(world.admin_a).post(
        url(world, "server-owner-groups/"), {"name": name, "owner_name": "Finance IT", "owner_email": email}
    )
    assert resp.status_code == 201, resp.content
    return resp.json()


def servers(world, **params):
    return world.client(world.viewer_a).get(url(world, "servers/"), params).json()


def test_servers_are_detected_from_the_os_name(world, demo):  # noqa: F811
    body = servers(world)
    expected = {str(o.asset_id) for o in current_observations(world.customer_a.id) if "server" in o.os_name.casefold()}
    assert expected and {r["asset_id"] for r in body["rows"]} == expected
    assert all(r["server_source"] == "detected" and r["owner_group_id"] is None for r in body["rows"])
    assert body["totals"]["servers"] == len(expected) == body["totals"]["unassigned"]
    everything = servers(world, scope="all")
    assert everything["count"] == current_observations(world.customer_a.id).count()


def test_marking_assigning_and_permissions(world, demo):  # noqa: F811
    group = make_group(world)
    rows = servers(world, scope="all")["rows"]
    workstation = next(r for r in rows if not r["is_server"])
    detected = next(r for r in rows if r["server_source"] == "detected")
    admin = world.client(world.admin_a)
    designate = url(world, "servers/designate/")
    assert admin.post(
        designate, {"assets": [workstation["asset_id"]], "marking": "server", "owner_group": group["id"]}, format="json"
    ).json() == {"updated": 1}
    assert (
        admin.post(designate, {"assets": [detected["asset_id"]], "marking": "not_server"}, format="json").status_code
        == 200
    )

    body = servers(world)
    ids = {r["asset_id"]: r for r in body["rows"]}
    assert ids[workstation["asset_id"]]["server_source"] == "marked"
    assert ids[workstation["asset_id"]]["owner_group"] == "Finance servers"
    assert ids[workstation["asset_id"]]["owner_email"] == "finance.it@example.test"
    assert detected["asset_id"] not in ids
    assert [r["asset_id"] for r in servers(world, owner_group=group["id"])["rows"]] == [workstation["asset_id"]]
    groups = world.client(world.viewer_a).get(url(world, "server-owner-groups/")).json()
    assert groups[0]["servers"] == 1

    # Viewers and engineers read only; other customers see nothing; foreign devices and groups are refused.
    assert (
        world.client(world.viewer_a).post(designate, {"assets": [detected["asset_id"]]}, format="json").status_code
        == 404
    )
    assert world.client(world.engineer_a).post(url(world, "server-owner-groups/"), {"name": "x"}).status_code == 404
    assert world.client(world.engineer_b).get(url(world, "servers/")).status_code == 404
    other = ServerOwnerGroup.objects.create(customer=world.customer_b, name="B", created_by=world.super_admin)
    refused = admin.post(designate, {"assets": [detected["asset_id"]], "owner_group": str(other.id)}, format="json")
    assert refused.status_code == 400
    assert (
        admin.post(
            designate, {"assets": ["00000000-0000-0000-0000-000000000001"], "marking": "server"}, format="json"
        ).status_code
        == 400
    )

    # Unique names; deleting a group unassigns its servers; contact details stay out of the audit trail.
    assert admin.post(url(world, "server-owner-groups/"), {"name": "finance servers"}).status_code == 400
    assert admin.delete(url(world, f"server-owner-groups/{group['id']}/")).status_code == 204
    assert servers(world, owner_group="none")["count"] == servers(world)["totals"]["servers"]
    events = AuditEvent.objects.filter(customer=world.customer_a, action__startswith="server")
    assert {"server_owner_group.created", "server.designated", "server_owner_group.deleted"} <= set(
        events.values_list("action", flat=True)
    )
    assert not any("finance.it@" in str(e.metadata) for e in events)


def test_patching_needs_are_explained(world, demo):  # noqa: F811
    from apps.patching.models import AppliedPolicyObservation

    first = servers(world)["rows"][0]
    AppliedPolicyObservation.objects.filter(asset_id=first["asset_id"]).update(patch_state="explicit_none")
    row = next(r for r in servers(world)["rows"] if r["asset_id"] == first["asset_id"])
    assert row["needs_attention"] and "No patch policy assigned in VSA X" in row["reasons"]
    assert servers(world, attention="true")["count"] >= 1


def test_report_per_owner_group(world, demo, django_capture_on_commit_callbacks):  # noqa: F811
    group = make_group(world)
    first = servers(world)["rows"][:2]
    world.client(world.admin_a).post(
        url(world, "servers/designate/"),
        {"assets": [r["asset_id"] for r in first], "owner_group": group["id"]},
        format="json",
    )
    run = request(
        world,
        django_capture_on_commit_callbacks,
        {"report_type": "server_owner_patching", "format": "csv", "filters": {"owner_group": group["id"]}},
    )
    _, rows = rows_of(world, run)
    assert sorted(r[3] for r in rows) == sorted(r["hostname"] for r in first)
    assert all(r[0] == "Finance servers" and r[2] == "finance.it@example.test" for r in rows)
    title = world.client(world.engineer_a).get(f"/api/v1/reports/{run}/").json()["title"]
    assert title == "Server patching - Finance servers"

    _, everyone = rows_of(
        world,
        request(world, django_capture_on_commit_callbacks, {"report_type": "server_owner_patching", "format": "csv"}),
    )
    assert len(everyone) == servers(world)["totals"]["servers"]
    assert everyone[0][0] == "Finance servers" and everyone[-1][0] == "No owner assigned"

    other = ServerOwnerGroup.objects.create(customer=world.customer_b, name="B", created_by=world.super_admin)
    resp = world.client(world.engineer_a).post(
        url(world, "reports/"),
        {"report_type": "server_owner_patching", "format": "csv", "filters": {"owner_group": str(other.id)}},
        format="json",
    )
    assert resp.status_code == 400


def test_scorecard_and_summary_include_servers(world, demo):  # noqa: F811
    from apps.reporting import scorecard

    group = make_group(world)
    first = servers(world)["rows"][0]
    world.client(world.admin_a).post(
        url(world, "servers/designate/"), {"assets": [first["asset_id"]], "owner_group": group["id"]}, format="json"
    )
    totals = servers(world)["totals"]
    assert totals["unassigned"] == totals["servers"] - 1 and "no_policy" in totals
    rows = {(r[0], r[1]): r for r in scorecard.rows(world.customer_a)}
    assert rows[("Servers", "Servers without an owner")][2] == totals["unassigned"]
    attention = rows[("Servers", "Servers needing patching or an upgrade")]
    assert attention[2] == totals["needs_attention"] and f"of {totals['servers']} servers" in attention[6]


def test_owner_report_can_be_scheduled_monthly_only_for_own_groups(world, demo):  # noqa: F811
    group = make_group(world)
    client = world.client(world.engineer_a)
    body = {"name": "Server patching - Finance", "report_type": "server_owner_patching", "format": "pdf"}
    created = client.post(
        url(world, "report-definitions/"), {**body, "filters": {"owner_group": group["id"]}}, format="json"
    )
    assert created.status_code == 201, created.content
    schedule = client.post(
        url(world, "report-schedules/"),
        {
            "definition": created.json()["id"],
            "frequency": "monthly",
            "day_of_month": 1,
            "time_of_day": "07:00",
            "timezone": "UTC",
        },
        format="json",
    )
    assert schedule.status_code == 201, schedule.content
    other = ServerOwnerGroup.objects.create(customer=world.customer_b, name="B", created_by=world.super_admin)
    refused = client.post(
        url(world, "report-definitions/"), {**body, "filters": {"owner_group": str(other.id)}}, format="json"
    )
    assert refused.status_code == 400
