"""VSA5-EXEC: approved group moves executed in VSA X - gated, once only, confirmed by read-back. Fixture writes."""

from __future__ import annotations

import pytest
import requests

from apps.audit.models import AuditEvent
from apps.integrations.vsa import fixtures
from apps.integrations.vsa.writer import MoveNotAvailable, VsaMoveWriter
from apps.inventory import move_execution
from apps.inventory.models import AssetObservation, GroupMoveExecution
from apps.inventory.queries import current_observations

from .test_automation import demo  # noqa: F401
from .test_script_values import resync

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_fixture_moves():
    fixtures.FIXTURE_MOVES.clear()
    yield
    fixtures.FIXTURE_MOVES.clear()


@pytest.fixture
def enabled(settings, demo):  # noqa: F811
    settings.VSA_GROUP_MOVE_EXECUTION_ENABLED = True
    demo.group_move_execution_enabled = True
    demo.save(update_fields=["group_move_execution_enabled"])
    return demo


def base(world):
    return f"/api/v1/customers/{world.customer_a.id}/group-moves/"


def approved(world, proposer=None, reviewer=None):
    proposer, reviewer = proposer or world.engineer_a, reviewer or world.admin_a
    obs = current_observations(world.customer_a.id).exclude(group_external_id="").order_by("hostname").first()
    options = world.client(proposer).get(f"{base(world)}options/", {"asset": str(obs.asset_id)}).json()
    target = options["groups"][0]
    proposal = (
        world.client(proposer)
        .post(base(world), {"asset": str(obs.asset_id), "target_group": target["id"], "reason": "Move to correct site"})
        .json()
    )
    review = world.client(reviewer).post(
        f"{base(world)}{proposal['id']}/review/", {"decision": "approved", "reason": "Checked policies in VSA"}
    )
    assert review.status_code == 200, review.content
    return proposal, obs, target


def test_off_until_the_integration_switch_is_set_in_the_portal(world, demo):  # noqa: F811
    # Server default: moves allowed; the per-integration switch (off by default) decides.
    proposal, _, _ = approved(world)
    assert proposal["execution_available"] is False
    assert "not enabled for this VSA X integration" in proposal["execution_unavailable_reason"]
    response = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert response.status_code == 400 and not fixtures.FIXTURE_MOVES


def test_server_emergency_stop_blocks_moves_and_nothing_is_sent(world, demo, settings):  # noqa: F811
    settings.VSA_GROUP_MOVE_EXECUTION_ENABLED = False
    demo.group_move_execution_enabled = True
    demo.save(update_fields=["group_move_execution_enabled"])
    proposal, _, _ = approved(world)
    assert proposal["execution_enabled"] is False and proposal["execution_available"] is False
    response = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert response.status_code == 400 and "switched off on this server" in str(response.json())
    assert "VSA_GROUP_MOVE_EXECUTION_ENABLED=false" in proposal["execution_unavailable_reason"]
    assert not GroupMoveExecution.objects.exists() and not fixtures.FIXTURE_MOVES


def test_integration_switch_is_also_required(world, demo, settings):  # noqa: F811
    settings.VSA_GROUP_MOVE_EXECUTION_ENABLED = True
    proposal, _, _ = approved(world)
    response = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert response.status_code == 400 and "not enabled for this VSA X integration" in str(response.json())


def test_approved_move_is_executed_once_and_confirmed(world, enabled):
    proposal, obs, target = approved(world)
    listed = world.client(world.admin_a).get(f"{base(world)}{proposal['id']}/").json()
    assert listed["execution_enabled"] is True and listed["execution_available"] is True and listed["execution"] is None
    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/").json()
    assert body["execution"]["state"] == "succeeded"
    assert body["execution"]["observed_group_id"] == target["external_id"]
    assert body["execution_enabled"] is False  # already executed
    again = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert again.status_code == 400 and "already sent" in str(again.json())
    assert len(fixtures.FIXTURE_MOVES) == 1
    actions = set(AuditEvent.objects.filter(target_id=proposal["id"]).values_list("action", flat=True))
    assert {"group_move.execute_started", "group_move.execute_succeeded"} <= actions
    # The next sync shows the device in its new group.
    resync(world, enabled)
    moved = current_observations(world.customer_a.id).get(asset_id=obs.asset_id)
    assert moved.group_external_id == target["external_id"]


def test_who_may_execute(world, enabled, settings):
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = True
    proposal, _, _ = approved(world, proposer=world.admin_a, reviewer=world.super_admin)
    url = f"{base(world)}{proposal['id']}/execute/"
    assert world.client(world.engineer_a).post(url).status_code == 404  # no approve capability
    assert world.client(world.engineer_b).post(url).status_code == 404  # other customer
    refused = world.client(world.admin_a).post(url)  # the requester
    assert refused.status_code == 400 and "proposed the move" in str(refused.json())
    assert world.client(world.super_admin).post(url).json()["execution"]["state"] == "succeeded"


def test_single_admin_approves_and_executes_own_move(world, enabled, settings):
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    proposal, _, target = approved(world, proposer=world.admin_a, reviewer=world.admin_a)
    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/").json()
    assert body["execution"]["state"] == "succeeded" and body["execution"]["observed_group_id"] == target["external_id"]
    started = AuditEvent.objects.get(action="group_move.execute_started", target_id=proposal["id"])
    assert started.metadata["by_requester"] is True


def test_changed_inventory_blocks_execution(world, enabled):
    proposal, obs, _ = approved(world)
    AssetObservation.objects.filter(pk=obs.pk).update(group_external_id="99999")
    response = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert response.status_code == 400 and "no longer in the group" in str(response.json())
    assert not GroupMoveExecution.objects.exists() and not fixtures.FIXTURE_MOVES


class _Timeout:
    def put(self, url, *, json, headers, auth):
        raise requests.Timeout()


class _AcceptedButNotApplied:
    def put(self, url, *, json, headers, auth):
        return fixtures.FakeResponse(200, {"Data": {"DeviceIdentifier": "x", "GroupId": json["GroupId"]}})


def test_timeout_is_unknown_and_verify_reads_back_without_resending(world, enabled):
    proposal, _, _ = approved(world)
    execution = move_execution.execute_move(world.customer_a, world.admin_a, proposal["id"], None, transport=_Timeout())
    assert execution.state == "unknown" and execution.error_code == "timeout_or_connection"
    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/verify/").json()
    # Read back: the device is still in its source group, so it was not moved. Nothing was sent again.
    assert body["execution"]["state"] == "failed" and body["execution"]["error_code"] == "still_in_source_group"
    assert not fixtures.FIXTURE_MOVES


def test_accepted_without_read_back_is_unverified_until_confirmed(world, enabled):
    proposal, obs, target = approved(world)
    execution = move_execution.execute_move(
        world.customer_a, world.admin_a, proposal["id"], None, transport=_AcceptedButNotApplied()
    )
    assert execution.state == "unverified"
    fixtures.FIXTURE_MOVES[(str(enabled.id), obs.asset.external_id)] = (target["external_id"], "x")
    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/verify/").json()
    assert body["execution"]["state"] == "succeeded"


def test_rejected_by_vsa_is_failed(world, enabled):
    proposal, _, _ = approved(world)
    execution = move_execution.execute_move(
        world.customer_a, world.admin_a, proposal["id"], None, transport=fixtures.FixtureWriteTransport(enabled, 403)
    )
    assert execution.state == "failed" and execution.http_status == 403


def test_live_integration_writes_with_its_token_or_an_optional_write_token(world, settings, monkeypatch):
    from apps.integrations.models import IntegrationInstance

    settings.VSA_GROUP_MOVE_EXECUTION_ENABLED = True
    inst = IntegrationInstance.objects.create(
        name="Live VSA",
        provider="vsa_x",
        base_url="https://vsa.example.com",
        enabled=True,
        group_move_execution_enabled=True,
        credential_ref="",
    )
    with pytest.raises(MoveNotAvailable, match="No VSA X API token"):
        VsaMoveWriter(inst)  # no token at all
    inst.credential_ref = "env:VSA_READ_TOKEN"
    monkeypatch.setenv("VSA_READ_TOKEN", "reader:secret-1")
    assert VsaMoveWriter(inst).auth == ("reader", "secret-1")  # one token is enough
    monkeypatch.setenv("VSA_WRITE_PROD", "writer:secret-2")
    inst.write_credential_ref = "env:VSA_WRITE_PROD"
    assert VsaMoveWriter(inst).auth == ("writer", "secret-2")  # an optional separate token wins
    inst.write_credential_ref = "env:DJANGO_SECRET_KEY"
    assert VsaMoveWriter(inst).auth == ("reader", "secret-1")  # never a server secret; falls back to the API token


def test_credential_references_cannot_name_server_secrets(world, monkeypatch, settings):
    """P5-07 finding 1: a reference may only name a connector variable, checked at the API and at resolution."""
    from apps.integrations.models import IntegrationInstance
    from apps.integrations.secrets import CredentialUnavailable, resolve_basic

    settings.CONNECTOR_ALLOWED_HOSTS = {**settings.CONNECTOR_ALLOWED_HOSTS, "vsa_x": ["vsa.example.com"]}
    inst = IntegrationInstance.objects.create(
        name="Live VSA", provider="vsa_x", base_url="https://vsa.example.com", enabled=False
    )
    client = world.client(world.super_admin)
    url = f"/api/v1/integrations/{inst.id}/"
    for bad in ("env:DJANGO_SECRET_KEY", "env:POSTGRES_PASSWORD", "env:VSA_WRITE_PROD"):
        resp = client.patch(url, {"credential_ref": bad}, format="json")
        assert resp.status_code == 400 and "credential_ref" in resp.content.decode(), bad
    for bad in ("env:DJANGO_SECRET_KEY", "env:VSA_TOKEN"):
        resp = client.patch(url, {"write_credential_ref": bad}, format="json")
        assert resp.status_code == 400 and "write_credential_ref" in resp.content.decode(), bad
    ok = client.patch(
        url, {"credential_ref": "env:VSA_TOKEN_PROD", "write_credential_ref": "env:VSA_WRITE_PROD"}, format="json"
    )
    assert ok.status_code == 200, ok.content
    assert "credential_ref" not in ok.json() and ok.json()["write_credential_configured"] is True
    monkeypatch.setenv("DJANGO_SECRET_KEY", "server-secret:value")
    with pytest.raises(CredentialUnavailable, match="VSA_, ITGLUE_ or AUTOTASK_"):
        resolve_basic("env:DJANGO_SECRET_KEY")  # a reference stored before this check is refused too


def test_unreachable_vsa_is_not_sent_and_the_move_can_be_sent_again(world, enabled, monkeypatch):
    """Live incident 2026-11-23: DNS failed before sending; it must say "not sent", not "outcome unknown"."""
    from apps.integrations.http import VendorUnavailable
    from apps.integrations.vsa import writer

    proposal, _, _ = approved(world)

    def no_dns(*args, **kwargs):
        raise VendorUnavailable("DNS resolution failed.")

    monkeypatch.setattr(writer, "check_egress", no_dns)
    resp = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert resp.status_code == 400
    assert "Nothing was sent" in str(resp.json()) and "DNS resolution failed" in str(resp.json())
    assert not GroupMoveExecution.objects.filter(proposal_id=proposal["id"]).exists()
    assert not fixtures.FIXTURE_MOVES
    assert AuditEvent.objects.filter(target_id=proposal["id"], action="group_move.execute_not_sent").exists()
    listed = world.client(world.admin_a).get(f"{base(world)}{proposal['id']}/").json()
    assert listed["execution_enabled"] is True and listed["execution"] is None
    waiting = world.client(world.admin_a).get(base(world), {"view": "to_move"}).json()
    assert proposal["id"] in {p["id"] for p in waiting["results"]}

    monkeypatch.undo()
    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/").json()
    assert body["execution"]["state"] == "succeeded" and len(fixtures.FIXTURE_MOVES) == 1


def test_move_confirmed_not_made_by_read_back_can_be_sent_again(world, enabled):
    proposal, _, target = approved(world)
    move_execution.execute_move(world.customer_a, world.admin_a, proposal["id"], None, transport=_Timeout())
    verified = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/verify/").json()
    assert verified["execution"]["error_code"] == "still_in_source_group"
    assert verified["execution_enabled"] is True  # still in its old group: sending again is safe
    waiting = world.client(world.admin_a).get(base(world), {"view": "to_move"}).json()
    assert proposal["id"] in {p["id"] for p in waiting["results"]}

    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/").json()
    assert body["execution"]["state"] == "succeeded"
    assert body["execution"]["observed_group_id"] == target["external_id"]
    started = AuditEvent.objects.filter(target_id=proposal["id"], action="group_move.execute_started").order_by(
        "created_at"
    )
    assert started.count() == 2 and started.last().metadata["retry_of"]["error_code"] == "still_in_source_group"


def test_move_rejected_by_vsa_is_not_sent_again(world, enabled):
    proposal, _, _ = approved(world)
    move_execution.execute_move(
        world.customer_a, world.admin_a, proposal["id"], None, transport=fixtures.FixtureWriteTransport(enabled, 403)
    )
    again = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert again.status_code == 400 and "already sent" in str(again.json())


class _AcceptedWithoutJson:
    """Live tenant 2026-11-23: HTTP 200 whose body is not the documented JSON (e.g. empty)."""

    def __init__(self, instance, apply=True):
        self.instance, self.apply = instance, apply

    def put(self, url, *, json, headers, auth):
        if self.apply:
            device = url.rstrip("/").split("/")[-2]
            fixtures.FIXTURE_MOVES[(str(self.instance.id), device)] = (str(json["GroupId"]), "x")
        return fixtures.FakeResponse(200, ValueError("no JSON body"))


def test_200_without_json_body_is_accepted_and_confirmed_by_read_back(world, enabled):
    proposal, _, target = approved(world)
    execution = move_execution.execute_move(
        world.customer_a, world.admin_a, proposal["id"], None, transport=_AcceptedWithoutJson(enabled)
    )
    assert execution.state == "succeeded" and execution.http_status == 200
    assert execution.observed_group_id == target["external_id"] and execution.error_code == ""


def test_200_without_documented_answer_and_device_not_moved_is_not_applied(world, enabled):
    """Live tenant 2026-11-23: HTTP 200, no documented JSON, read-back shows the old group -> not moved, resendable."""
    proposal, obs, target = approved(world)
    execution = move_execution.execute_move(
        world.customer_a, world.admin_a, proposal["id"], None, transport=_AcceptedWithoutJson(enabled, apply=False)
    )
    assert execution.state == "failed" and execution.error_code == "accepted_not_applied"
    assert execution.observed_group_id == obs.group_external_id
    event = AuditEvent.objects.get(target_id=proposal["id"], action="group_move.execute_failed")
    assert event.metadata["answer"]["documented_answer"] is False
    assert world.client(world.admin_a).get(base(world), {"view": "to_verify"}).json()["results"] == []
    waiting = world.client(world.admin_a).get(base(world), {"view": "to_move"}).json()
    assert [p["id"] for p in waiting["results"]] == [proposal["id"]]
    # Once the cause is fixed the same move can be sent again.
    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/").json()
    assert body["execution"]["state"] == "succeeded"
    assert body["execution"]["observed_group_id"] == target["external_id"]


def test_documented_answer_not_yet_visible_stays_unverified_and_listed_to_verify(world, enabled):
    proposal, obs, target = approved(world)
    execution = move_execution.execute_move(
        world.customer_a, world.admin_a, proposal["id"], None, transport=_AcceptedButNotApplied()
    )
    assert execution.state == "unverified"
    listed = world.client(world.admin_a).get(base(world), {"view": "to_verify"}).json()
    assert [p["id"] for p in listed["results"]] == [proposal["id"]]
    fixtures.FIXTURE_MOVES[(str(enabled.id), obs.asset.external_id)] = (target["external_id"], "x")
    body = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/verify/").json()
    assert body["execution"]["state"] == "succeeded"
    assert world.client(world.admin_a).get(base(world), {"view": "to_verify"}).json()["results"] == []
