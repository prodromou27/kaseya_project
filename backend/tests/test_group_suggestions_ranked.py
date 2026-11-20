"""CIDR-02: network-first hints on the onboarding group; synthetic evidence only."""

# ruff: noqa: F811

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.customers.models import CustomerSourceMapping
from apps.inventory.models import AssetObservation, GroupNode, GroupSetting, IpAddressObservation

from .test_group_suggestions import base, observation, rule, second_source
from .test_vsa1_hierarchy_network import env, synced  # noqa: F401

pytestmark = pytest.mark.django_db


def prepare(world, synced):
    source = observation(world)
    source.hostname = "NIC-WS001"
    source.save(update_fields=["hostname"])
    GroupSetting.objects.create(
        customer=world.customer_a, integration_instance=synced["inst"], group_external_id="51", is_onboarding=True
    )
    GroupNode.objects.filter(generation=source.generation, external_id="61").update(name="NIC Office")
    return source


def device_hints(world, source):
    return world.client(world.viewer_a).get(base(world) + "/group-moves/options/", {"asset": source.asset_id})


def group_url(world, synced):
    return base(world) + f"/groups/51/suggestions/?instance={synced['inst'].id}"


def test_network_beats_names_and_approved_beats_observed(world, synced):
    source = prepare(world, synced)
    data = device_hints(world, source).json()
    assert [(g["external_id"], g["basis"]) for g in data["suggestions"]] == [
        ("52", "observed_subnet"),
        ("61", "naming"),
    ]
    assert data["suggestions"][0]["matches"][0]["peer_devices"] == 1
    assert data["suggestions_ambiguous"] is True
    rule(world, synced, group="61")
    data = device_hints(world, source).json()
    assert [(g["external_id"], g["basis"]) for g in data["suggestions"]] == [
        ("61", "approved_subnet"),
        ("52", "observed_subnet"),
    ]
    assert data["execution_enabled"] is False
    assert data["suggestions"][0]["site"] == "6"


def test_peer_hostname_prefix_is_weaker_and_generic_names_are_ignored(world, synced):
    source = prepare(world, synced)
    source.adapters.all().delete()
    AssetObservation.objects.filter(generation=source.generation, group_external_id="52").update(hostname="NIC-WS999")
    data = device_hints(world, source).json()
    assert {g["external_id"] for g in data["suggestions"]} == {"52", "61"}
    assert all(g["basis"] == "naming" and not g["matches"] for g in data["suggestions"])
    source.hostname = "DESKTOP-123"
    source.save()
    AssetObservation.objects.filter(generation=source.generation, group_external_id="52").update(hostname="DESKTOP-456")
    assert device_hints(world, source).json()["suggestions"] == []


@pytest.mark.parametrize("bad_cidr", ["bad", "0.0.0.0/0", "10.0.1.10/24"])
def test_invalid_observed_or_approved_networks_never_promote_names(world, synced, bad_cidr):
    source = prepare(world, synced)
    IpAddressObservation.objects.filter(adapter__observation__group_external_id="52", customer=world.customer_a).update(
        network_cidr=bad_cidr
    )
    rule(world, synced, cidr=bad_cidr)
    assert [(g["external_id"], g["basis"]) for g in device_hints(world, source).json()["suggestions"]] == [
        ("61", "naming")
    ]


def test_missing_network_status_does_not_use_leftover_addresses(world, synced):
    source = prepare(world, synced)
    AssetObservation.objects.filter(pk=source.pk).update(network_status="not_collected")
    assert {g["basis"] for g in device_hints(world, source).json()["suggestions"]} == {"naming"}


def test_ipv6_approved_subnet_matches_without_inventing_an_observed_prefix(world, synced):
    source = prepare(world, synced)
    IpAddressObservation.objects.filter(adapter__observation=source).update(
        address="2001:db8::10", version=6, kind="private"
    )
    rule(world, synced, cidr="2001:db8::/64")
    data = device_hints(world, source).json()
    assert data["suggestions"][0]["basis"] == "approved_subnet"
    assert data["suggestions"][0]["matches"][0]["addresses"] == ["2001:db8::10"]


def test_group_endpoint_is_paged_scoped_and_has_constant_query_count(world, synced):
    source = prepare(world, synced)
    client = world.client(world.viewer_a)
    url = group_url(world, synced)
    with CaptureQueriesContext(connection) as one:
        response = client.get(url + "&page_size=1")
    data = response.json()
    assert response.status_code == 200 and data["is_onboarding"] is True
    assert data["count"] == 3 and len(data["results"]) == 1 and data["next"]
    with CaptureQueriesContext(connection) as two:
        data2 = client.get(url + "&page_size=3").json()
    assert len(two) <= len(one) + 1
    assert len(data2["results"]) == 3
    row = next(r for r in data2["results"] if r["asset_id"] == str(source.asset_id))
    assert row["suggestions"][0]["basis"] == "observed_subnet"
    assert client.get(url + "&search=NIC").json()["count"] == 1
    assert client.get(url + "&search=absent").json()["count"] == 0
    assert client.get(url + "&page=999").status_code == 404
    assert client.get(url + "&search=" + "x" * 101).status_code == 400
    assert world.client(world.engineer_b).get(url).status_code == 404
    assert client.get(base(world) + "/groups/51/suggestions/?instance=invalid").status_code == 404
    GroupSetting.objects.filter(customer=world.customer_a).update(is_onboarding=False)
    assert client.get(url).json()["results"] == []


def test_foreign_source_organization_and_onboarding_groups_are_excluded(world, synced):
    source = prepare(world, synced)
    foreign = second_source(world)
    GroupNode.objects.filter(generation__integration_instance=foreign).update(name="NIC foreign")
    GroupNode.objects.filter(generation=source.generation, external_id="61").update(organization_external_id="999")
    data = device_hints(world, source).json()
    assert [g["external_id"] for g in data["suggestions"]] == ["52"]
    GroupSetting.objects.create(
        customer=world.customer_a, integration_instance=synced["inst"], group_external_id="52", is_onboarding=True
    )
    assert device_hints(world, source).json()["suggestions"] == []


def test_revoked_and_stale_snapshots_fail_closed(world, synced):
    source = prepare(world, synced)
    source.generation.published_at = timezone.now() - timedelta(days=365)
    source.generation.save()
    assert world.client(world.viewer_a).get(group_url(world, synced)).status_code == 400
    assert device_hints(world, source).status_code == 400
    CustomerSourceMapping.objects.filter(pk=source.generation.mapping_id).update(mapping_status="proposed")
    assert world.client(world.viewer_a).get(group_url(world, synced)).status_code == 404
    assert device_hints(world, source).status_code == 404


def names_only(world, source):
    source.adapters.all().delete()
    return device_hints(world, source).json()["suggestions"]


def test_department_prefix_without_separator_matches_destination_peers(world, synced):
    source = prepare(world, synced)
    source.hostname = "DEPARTMENTUSERSX"
    source.save(update_fields=["hostname"])
    AssetObservation.objects.filter(generation=source.generation, group_external_id="52").update(
        hostname="DEPARTMENTUSERSA"
    )
    hints = names_only(world, source)
    assert [g["external_id"] for g in hints] == ["52"]
    assert "Name starts with 'DEPARTMENTUS' like 1 of 1 device(s) in this group." in hints[0]["naming_evidence"]


def test_leading_letters_match_the_start_of_a_group_name(world, synced):
    source = prepare(world, synced)
    source.hostname = "FINUSR01"
    source.save(update_fields=["hostname"])
    GroupNode.objects.filter(generation=source.generation, external_id="61").update(name="Finance")
    hints = names_only(world, source)
    assert [g["external_id"] for g in hints] == ["61"]
    assert hints[0]["naming_evidence"] == ["Name starts with 'FIN', the start of the group name 'Finance'."]


def test_longer_shared_prefix_ranks_first_and_wins_the_plan(world, synced):
    source = prepare(world, synced)
    source.hostname = "DEPTSALESX"
    source.save(update_fields=["hostname"])
    AssetObservation.objects.filter(generation=source.generation, group_external_id="52").update(hostname="DEPTSALES7")
    GroupNode.objects.filter(generation=source.generation, external_id="61").update(name="Dept Office")
    hints = names_only(world, source)
    assert [g["external_id"] for g in hints] == ["52", "61"]
    assert hints[0]["naming_strength"] > hints[1]["naming_strength"]
    plan = world.client(world.viewer_a).get(base(world) + f"/groups/51/suggestions/plan/?instance={synced['inst'].id}")
    assert plan.status_code == 200, plan.content
    body = plan.json()
    placed = {d["hostname"]: dest["external_id"] for dest in body["destinations"] for d in dest["devices"]}
    assert placed["DEPTSALESX"] == "52"
    for dest in body["destinations"]:
        assert GroupNode.objects.filter(pk=dest["id"], external_id=dest["external_id"]).exists()
    total = sum(len(d["devices"]) for d in body["destinations"]) + len(body["ambiguous"]) + len(body["unmatched"])
    assert total == body["devices"] and body["truncated"] is False


def test_plan_is_scoped_and_needs_an_onboarding_group(world, synced):
    url = base(world) + f"/groups/51/suggestions/plan/?instance={synced['inst'].id}"
    assert world.client(world.viewer_a).get(url).json()["is_onboarding"] is False
    prepare(world, synced)
    assert world.client(world.engineer_b).get(url).status_code == 404
