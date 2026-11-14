"""LIST-01: persisted presentation, existing ownership boundaries and source-qualified navigation."""

import pytest

from apps.audit.models import AuditEvent
from apps.inventory.models import GroupSetting

from .test_group_suggestions import second_source
from .test_vsa1_hierarchy_network import env, synced  # noqa: F401

pytestmark = pytest.mark.django_db


def url(customer):
    return f"/api/v1/customers/{customer.id}/saved-views/"


def test_named_layout_roundtrip_owner_update_and_delete_are_audited(world):
    client = world.client(world.engineer_a)
    body = {
        "name": "Offline investigation",
        "view_type": "assets",
        "filters": {"offline": "true", "ordering": "-hostname"},
        "layout": {"columns": ["hostname", "group_name"], "density": "comfortable", "page_size": 100},
    }
    response = client.post(url(world.customer_a), body, format="json")
    assert response.status_code == 201, response.content
    row = response.json()
    assert client.post(url(world.customer_a), body, format="json").status_code == 400
    assert row["layout"] == body["layout"]
    detail = f"{url(world.customer_a)}{row['id']}/"
    assert client.get(detail).json()["layout"] == body["layout"]
    assert world.client(world.viewer_a).get(detail).status_code == 404
    assert world.client(world.engineer_b).get(detail).status_code == 404
    assert client.patch(detail, {"shared": True}, format="json").status_code == 200
    viewer = world.client(world.viewer_a)
    assert viewer.get(detail).json()["layout"] == body["layout"]
    assert viewer.patch(detail, {"layout": {"columns": ["software"]}}, format="json").status_code == 403
    assert viewer.delete(detail).status_code == 403
    assert client.patch(detail, {"layout": {}}, format="json").json()["layout"] == {}
    assert client.delete(detail).status_code == 204
    assert client.get(detail).status_code == 404
    assert set(AuditEvent.objects.filter(target_id=row["id"]).values_list("action", flat=True)) == {
        "saved_view.created",
        "saved_view.updated",
        "saved_view.deleted",
    }


@pytest.mark.parametrize(
    "layout",
    [
        [],
        "x",
        {"sql": "x"},
        {"columns": []},
        {"columns": ["password"]},
        {"columns": ["hostname", "hostname"]},
        {"columns": [{}]},
        {"density": "huge"},
        {"page_size": 500},
        {"page_size": True},
        {"page_size": "50"},
    ],
)
def test_malformed_and_unsupported_layouts_are_rejected(world, layout):
    response = world.client(world.engineer_a).post(
        url(world.customer_a), {"name": "Invalid", "view_type": "assets", "layout": layout}, format="json"
    )
    assert response.status_code == 400


def test_filter_only_legacy_saved_views_keep_empty_layout_and_default_contract(world):
    client = world.client(world.engineer_a)
    response = client.post(
        url(world.customer_a),
        {"name": "Legacy filters", "view_type": "assets", "filters": {"os": "Windows"}},
        format="json",
    )
    assert response.status_code == 201 and response.json()["layout"] == {}
    assert (
        client.post(
            url(world.customer_a),
            {"name": "Wrong type", "view_type": "software", "layout": {"density": "compact"}},
            format="json",
        ).status_code
        == 400
    )


def test_source_facets_and_group_purpose_keep_customer_and_instance_identity(world, synced):  # noqa: F811
    other = second_source(world)
    GroupSetting.objects.create(
        customer=world.customer_a, integration_instance=other, group_external_id="52", is_onboarding=True
    )
    client = world.client(world.engineer_a)
    base = f"/api/v1/customers/{world.customer_a.id}"
    facets = client.get(f"{base}/assets/facets/").json()
    groups = facets["groups"]
    assert {g["generation__integration_instance_id"] for g in groups} == {str(synced["inst"].id), str(other.id)}
    assert all(g["group_external_id"] != "81" for g in groups)
    assert all(site["site_external_id"] != "8" for site in facets["sites"])
    tree = client.get(f"{base}/hierarchy/").json()
    flags = {
        (g["instance_id"], g["external_id"]): g["is_onboarding"]
        for o in tree["organizations"]
        for s in o["sites"]
        for g in s["groups"]
    }
    assert flags[(str(other.id), "52")] is True
    assert flags[(str(synced["inst"].id), "52")] is False
    row = client.get(f"{base}/assets/", {"page_size": 25}).json()["results"][0]
    assert row["instance_id"] in {str(other.id), str(synced["inst"].id)}
    assert world.client(world.engineer_b).get(f"{base}/assets/facets/").status_code == 404
