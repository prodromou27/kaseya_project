"""MOV-02: move a pasted or uploaded device list to one group. The check records and sends nothing."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.integrations.vsa import fixtures
from apps.inventory.models import GroupMoveRequest, GroupNode
from apps.inventory.queries import current_observations

from .test_automation import demo  # noqa: F401
from .test_group_move_execution import enabled, single_admin  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_fixture_moves():
    fixtures.FIXTURE_MOVES.clear()
    yield
    fixtures.FIXTURE_MOVES.clear()


def url(world, path):
    return f"/api/v1/customers/{world.customer_a.id}/group-moves/{path}/"


def setup_list(world):
    obs = list(current_observations(world.customer_a.id).exclude(group_external_id="").order_by("hostname"))
    target = (
        GroupNode.objects.filter(
            customer=world.customer_a,
            generation=obs[0].generation,
            organization_external_id=obs[0].organization_external_id,
            is_active=True,
        )
        .exclude(external_id=obs[0].group_external_id)
        .first()
    )
    inside = next(o for o in obs if o.group_external_id == target.external_id)
    outside = [o for o in obs if o.group_external_id != target.external_id]
    return target, inside, outside


def test_check_list_says_what_moves_and_skips_devices_not_in_vsa(world, demo):  # noqa: F811
    target, inside, outside = setup_list(world)
    text = "\n".join(
        [
            outside[0].hostname,
            outside[1].hostname.lower(),
            inside.hostname,
            "GHOST-PC-404",
            outside[0].hostname,
            "bad name!",
        ]
    )
    before = (GroupMoveRequest.objects.count(), AuditEvent.objects.count())
    resp = world.client(world.engineer_a).post(
        url(world, "check-list"), {"text": text, "target_group": str(target.id)}, format="json"
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert [r["status"] for r in body["rows"]] == [
        "move",
        "move",
        "already_there",
        "not_in_vsa",
        "duplicate",
        "invalid",
    ]
    assert body["to_move"] == 2 and body["counts"]["not_in_vsa"] == 1
    assert body["rows"][3]["note"].startswith("Not in VSA X (not onboarded)")
    assert body["rows"][0]["asset_id"] == str(outside[0].asset_id)
    assert body["target"]["id"] == str(target.id)
    assert (GroupMoveRequest.objects.count(), AuditEvent.objects.count()) == before  # nothing recorded


def test_uploaded_file_with_or_without_a_header(world, demo):  # noqa: F811
    target, _inside, outside = setup_list(world)
    for content in (f"Hostname,Owner\n{outside[0].hostname},x\n", f"{outside[0].hostname}\n{outside[1].hostname}\n"):
        upload = SimpleUploadedFile("devices.csv", content.encode(), content_type="text/csv")
        resp = world.client(world.engineer_a).post(
            url(world, "check-list"), {"file": upload, "target_group": str(target.id)}, format="multipart"
        )
        assert resp.status_code == 200, resp.content
        assert all(r["status"] == "move" for r in resp.json()["rows"])


def test_destinations_and_permissions_and_tenant_isolation(world, demo):  # noqa: F811
    target, _inside, outside = setup_list(world)
    groups = world.client(world.viewer_a).get(url(world, "destinations")).json()["groups"]
    assert str(target.id) in {g["id"] for g in groups}
    body = {"text": outside[0].hostname, "target_group": str(target.id)}
    assert world.client(world.viewer_a).post(url(world, "check-list"), body, format="json").status_code in (403, 404)
    other = world.client(world.engineer_b).post(
        f"/api/v1/customers/{world.customer_b.id}/group-moves/check-list/", body, format="json"
    )
    assert other.status_code == 400 and "target_group" in other.json()["error"]["details"]
    assert world.client(world.engineer_b).post(url(world, "check-list"), body, format="json").status_code in (403, 404)


def test_admin_list_check_allows_one_step_moves_and_each_move_uses_the_normal_step(world, enabled, single_admin):  # noqa: F811
    target, _inside, outside = setup_list(world)
    body = (
        world.client(world.admin_a)
        .post(url(world, "check-list"), {"text": outside[0].hostname, "target_group": str(target.id)}, format="json")
        .json()
    )
    assert body["move_now_allowed"] is True
    eng = (
        world.client(world.engineer_a)
        .post(url(world, "check-list"), {"text": outside[0].hostname, "target_group": str(target.id)}, format="json")
        .json()
    )
    assert eng["move_now_allowed"] is False
    row = body["rows"][0]
    moved = world.client(world.admin_a).post(
        url(world, "move-now"), {"asset": row["asset_id"], "target_group": target.id.hex}, format="json"
    )
    assert moved.status_code == 200 and moved.json()["execution"]["state"] == "succeeded"
