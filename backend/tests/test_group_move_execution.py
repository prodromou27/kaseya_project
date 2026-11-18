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


def test_switched_off_by_default_and_nothing_is_sent(world, demo):  # noqa: F811
    proposal, _, _ = approved(world)
    assert proposal["execution_enabled"] is False
    response = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert response.status_code == 400 and "switched off on this server" in str(response.json())
    assert not GroupMoveExecution.objects.exists() and not fixtures.FIXTURE_MOVES


def test_integration_switch_is_also_required(world, demo, settings):  # noqa: F811
    settings.VSA_GROUP_MOVE_EXECUTION_ENABLED = True
    proposal, _, _ = approved(world)
    response = world.client(world.admin_a).post(f"{base(world)}{proposal['id']}/execute/")
    assert response.status_code == 400 and "not enabled for this VSA X integration" in str(response.json())


def test_approved_move_is_executed_once_and_confirmed(world, enabled):
    proposal, obs, target = approved(world)
    listed = world.client(world.admin_a).get(f"{base(world)}{proposal['id']}/").json()
    assert listed["execution_enabled"] is True and listed["execution"] is None
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


def test_who_may_execute(world, enabled):
    proposal, _, _ = approved(world, proposer=world.admin_a, reviewer=world.super_admin)
    url = f"{base(world)}{proposal['id']}/execute/"
    assert world.client(world.engineer_a).post(url).status_code == 404  # no approve capability
    assert world.client(world.engineer_b).post(url).status_code == 404  # other customer
    refused = world.client(world.admin_a).post(url)  # the requester
    assert refused.status_code == 400 and "proposed the move" in str(refused.json())
    assert world.client(world.super_admin).post(url).json()["execution"]["state"] == "succeeded"


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
