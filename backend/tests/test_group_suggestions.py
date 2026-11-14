"""Synthetic source-scoped CIDR hints, temporary onboarding groups and administrator controls."""

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.customers.models import CustomerSourceMapping
from apps.integrations.models import IntegrationInstance
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.inventory.models import AssetObservation, ExpectedSubnet, GroupNode

from .test_vsa1_hierarchy_network import asset, env, run, synced  # noqa: F401


def second_source(world):
    instance = IntegrationInstance.objects.create(
        name="Second fixture", provider="vsa_x", base_url="https://second.invalid", is_fixture=True, enabled=True
    )
    mapping = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=instance,
        external_org_id="11",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    assert run(mapping, world.engineer_a, FixtureVsaTransport([asset(99, 11, group=52)])).state == "completed"
    return instance


pytestmark = pytest.mark.django_db


def base(world):
    return f"/api/v1/customers/{world.customer_a.id}"


def observation(world):
    return AssetObservation.objects.get(customer=world.customer_a, hostname="SHARED-NAME")


def hints(world):
    return world.client(world.viewer_a).get(
        base(world) + "/group-moves/options/", {"asset": observation(world).asset_id}
    )


def rule(world, synced, group="52", cidr="10.0.1.0/24", state="approved"):  # noqa: F811
    return ExpectedSubnet.objects.create(
        customer=world.customer_a,
        integration_instance=synced["inst"],
        scope_type="group",
        scope_external_id=group,
        cidr=cidr,
        reason="Approved LAN plan",
        state=state,
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
    )


def test_onboarding_purpose_authorized_audited_and_manual_hints(world, synced):  # noqa: F811
    url = base(world) + f"/groups/51/settings/?instance={synced['inst'].id}"
    admin = world.client(world.admin_a)
    assert admin.post(url, {}).status_code == 400
    assert world.client(world.viewer_a).post(url, {"is_onboarding": True}).status_code == 404
    assert world.client(world.engineer_b).post(url, {"is_onboarding": True}).status_code == 404
    assert admin.post(url, {"is_onboarding": True}).status_code == 200
    assert admin.get(url).json() == {"is_onboarding": True}
    rule(world, synced)
    data = hints(world).json()
    assert data["source_is_onboarding"] is True
    assert data["execution_enabled"] is False
    assert data["suggestions"][0]["external_id"] == "52"
    assert data["suggestions"][0]["matches"] == [{"cidr": "10.0.1.0/24", "addresses": ["10.0.1.10"]}]
    assert "manually" in data["suggestion_note"]
    assert AuditEvent.objects.filter(customer=world.customer_a, action="group_setting.updated").count() == 1


def test_missing_network_and_unapproved_retired_legacy_rules_never_suggest(world, synced):  # noqa: F811
    rule(world, synced, state="proposed")
    rule(world, synced, cidr="10.0.0.0/16", state="retired")
    ExpectedSubnet.objects.create(
        customer=world.customer_a,
        scope_type="group",
        scope_external_id="52",
        cidr="10.0.0.0/8",
        reason="Unqualified legacy",
        state="approved",
        proposed_by=world.admin_a,
    )
    assert hints(world).json()["suggestions"] == []
    rule(world, synced, cidr="10.0.1.0/24", state="rejected")
    assert hints(world).json()["suggestions"] == []
    observation(world).adapters.all().delete()
    assert hints(world).json()["suggestions"] == []


def test_overlap_is_ambiguous_and_onboarding_destinations_are_not_suggested(world, synced):  # noqa: F811
    rule(world, synced)
    rule(world, synced, group="61", cidr="10.0.0.0/16")
    data = hints(world).json()
    assert data["suggestions_ambiguous"] is True
    assert {g["external_id"] for g in data["suggestions"]} == {"52", "61"}
    url = base(world) + f"/groups/52/settings/?instance={synced['inst'].id}"
    world.client(world.admin_a).post(url, {"is_onboarding": True})
    data = hints(world).json()
    assert data["suggestions_ambiguous"] is False
    assert [g["external_id"] for g in data["suggestions"]] == ["61"]


def test_subnets_require_qualified_source_when_group_ids_collide(world, synced):  # noqa: F811
    other = second_source(world)
    url = base(world) + "/expected-subnets/"
    body = {"scope_type": "group", "scope_external_id": "52", "cidr": "10.0.1.0/24", "reason": "Destination LAN"}
    admin = world.client(world.admin_a)
    assert admin.post(url, body).status_code == 400
    body["integration_instance"] = str(synced["inst"].id)
    created = admin.post(url, body)
    assert created.status_code == 201, created.content
    assert created.json()["integration_instance"] == str(synced["inst"].id)
    assert admin.post(url, body).status_code == 400
    body["integration_instance"] = str(other.id)
    assert admin.post(url, body).status_code == 201
    foreign = GroupNode.objects.filter(customer=world.customer_b).first()
    body["integration_instance"] = str(foreign.generation.integration_instance_id)
    assert admin.post(url, body).status_code == 400
    rule_obj = ExpectedSubnet.objects.get(pk=created.json()["id"])
    rule_obj.state = "approved"
    rule_obj.save()
    assert len(hints(world).json()["suggestions"]) == 1
