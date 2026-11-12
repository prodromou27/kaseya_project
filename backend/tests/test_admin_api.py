"""P0-06 customer admin: role matrix, membership delegation, mapping review, integration egress policy."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.customers.models import Customer, CustomerMembership, CustomerSourceMapping
from apps.integrations.models import IntegrationInstance

from .factories import IntegrationFactory, MappingFactory, UserFactory

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- customers CRUD role matrix


@pytest.mark.parametrize("who", ["admin_a", "engineer_a", "viewer_a", "outsider"])
def test_only_super_admin_creates_updates_archives_customers(world, who):
    client = world.client(getattr(world, who))
    assert client.post("/api/v1/customers/", {"code": "NEW", "name": "New"}).status_code == 403
    assert client.patch(f"/api/v1/customers/{world.customer_a.id}/", {"name": "Hacked"}).status_code == 403
    assert client.delete(f"/api/v1/customers/{world.customer_a.id}/").status_code == 403
    world.customer_a.refresh_from_db()
    assert world.customer_a.name == "Acme Ltd" and world.customer_a.status == "active"


def test_super_admin_customer_lifecycle_is_audited(world):
    client = world.client(world.super_admin)
    resp = client.post("/api/v1/customers/", {"code": "gamma", "name": "Gamma"})
    assert resp.status_code == 201 and resp.json()["code"] == "GAMMA"
    cid = resp.json()["id"]
    assert client.patch(f"/api/v1/customers/{cid}/", {"status": "active"}).status_code == 200
    resp = client.delete(f"/api/v1/customers/{cid}/")
    assert resp.status_code == 200 and resp.json()["status"] == "archived"
    assert Customer.objects.filter(pk=cid).exists()  # archived, not deleted
    actions = set(AuditEvent.objects.filter(customer_id=cid).values_list("action", flat=True))
    assert {"customer.created", "customer.updated", "customer.archived"} <= actions


def test_customer_code_validation_and_uniqueness(world):
    client = world.client(world.super_admin)
    assert client.post("/api/v1/customers/", {"code": "acme", "name": "Dup"}).status_code == 400
    assert client.post("/api/v1/customers/", {"code": "bad code!", "name": "X"}).status_code == 400


def test_capabilities_reported_per_customer(world):
    data = world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/").json()
    assert data["my_capabilities"] == ["customer.read"]


# ---------------------------------------------------------------- memberships / delegation


def test_customer_admin_grants_and_revokes_engineer(world):
    newbie = UserFactory(email="new@example.test")
    client = world.client(world.admin_a)
    url = f"/api/v1/customers/{world.customer_a.id}/memberships/"
    resp = client.post(url, {"email": "NEW@example.test", "role": "engineer"})
    assert resp.status_code == 201, resp.content
    mid = resp.json()["id"]
    assert world.client(newbie).get(f"/api/v1/customers/{world.customer_a.id}/").status_code == 200
    assert client.delete(f"{url}{mid}/").status_code == 204
    assert world.client(newbie).get(f"/api/v1/customers/{world.customer_a.id}/").status_code == 404
    actions = list(AuditEvent.objects.filter(target_id=mid).values_list("action", flat=True))
    assert sorted(actions) == ["membership.granted", "membership.revoked"]


def test_customer_admin_cannot_grant_admin_or_touch_admins(world):
    UserFactory(email="new@example.test")
    client = world.client(world.admin_a)
    url = f"/api/v1/customers/{world.customer_a.id}/memberships/"
    assert client.post(url, {"email": "new@example.test", "role": "admin"}).status_code == 403
    other_admin = CustomerMembership.objects.create(
        customer=world.customer_a,
        user=UserFactory(),
        role=CustomerMembership._meta.get_field("role").related_model.objects.get(key="admin"),
    )
    assert client.patch(f"{url}{other_admin.id}/", {"role": "viewer"}).status_code == 403
    assert client.delete(f"{url}{other_admin.id}/").status_code == 403


def test_cannot_modify_own_membership(world):
    m = CustomerMembership.objects.get(user=world.admin_a)
    client = world.client(world.admin_a)
    url = f"/api/v1/customers/{world.customer_a.id}/memberships/{m.id}/"
    assert client.patch(url, {"role": "viewer"}).status_code == 403
    assert client.delete(url).status_code == 403


def test_cannot_grant_global_role_via_membership(world):
    UserFactory(email="new@example.test")
    resp = world.client(world.super_admin).post(
        f"/api/v1/customers/{world.customer_a.id}/memberships/", {"email": "new@example.test", "role": "super_admin"}
    )
    assert resp.status_code == 400


def test_engineer_cannot_manage_members(world):
    url = f"/api/v1/customers/{world.customer_a.id}/memberships/"
    assert world.client(world.engineer_a).get(url).status_code == 404


def test_customer_admin_cannot_manage_other_customer_members(world):
    url = f"/api/v1/customers/{world.customer_b.id}/memberships/"
    resp = world.client(world.admin_a).post(url, {"email": world.outsider.email, "role": "engineer"})
    assert resp.status_code == 404
    assert not CustomerMembership.objects.filter(user=world.outsider).exists()


def test_membership_id_from_other_customer_not_reachable_via_own_customer_route(world):
    mb = CustomerMembership.objects.get(user=world.engineer_b)
    url = f"/api/v1/customers/{world.customer_a.id}/memberships/{mb.id}/"
    resp = world.client(world.admin_a).delete(url)
    assert resp.status_code == 404
    assert CustomerMembership.objects.get(pk=mb.pk).is_active


# ---------------------------------------------------------------- source mappings


def test_mapping_proposal_and_super_admin_review(world):
    inst = IntegrationFactory()
    admin = world.client(world.admin_a)
    resp = admin.post(
        f"/api/v1/customers/{world.customer_a.id}/mappings/",
        {"integration_instance": str(inst.id), "external_org_id": " 1001 ", "external_org_name": "Acme (VSA)"},
    )
    assert resp.status_code == 201 and resp.json()["mapping_status"] == "proposed"
    mid = resp.json()["id"]
    assert resp.json()["external_org_id"] == "1001"
    # customer admin cannot approve
    assert admin.post(f"/api/v1/mappings/{mid}/approve/").status_code == 403
    sa = world.client(world.super_admin)
    assert [m["id"] for m in sa.get("/api/v1/mappings/", {"status": "proposed"}).json()["results"]] == [mid]
    resp = sa.post(f"/api/v1/mappings/{mid}/approve/", {"note": "verified in VSA console"})
    assert resp.status_code == 200 and resp.json()["mapping_status"] == "approved"
    assert resp.json()["reviewed_by"] == world.super_admin.email
    assert sa.post(f"/api/v1/mappings/{mid}/approve/").status_code == 400  # not proposed any more
    assert sa.post(f"/api/v1/mappings/{mid}/revoke/").json()["mapping_status"] == "revoked"
    assert AuditEvent.objects.filter(target_id=mid).count() == 3


def test_source_org_cannot_map_to_two_customers(world):
    inst = IntegrationFactory()
    MappingFactory(customer=world.customer_a, integration_instance=inst, external_org_id="42")
    resp = world.client(world.super_admin).post(
        f"/api/v1/customers/{world.customer_b.id}/mappings/",
        {"integration_instance": str(inst.id), "external_org_id": "42"},
    )
    assert resp.status_code == 400
    assert "Acme" not in resp.content.decode()  # no leak of which customer holds it


def test_db_constraints_on_mappings(world):
    inst = IntegrationFactory()
    MappingFactory(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="7",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at="2026-01-01T00:00:00Z",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        MappingFactory(customer=world.customer_b, integration_instance=inst, external_org_id="7")
    with pytest.raises(IntegrityError), transaction.atomic():
        CustomerSourceMapping.objects.create(
            customer=world.customer_b, integration_instance=inst, external_org_id="8", mapping_status="approved"
        )  # approved without reviewer
    # rejected mappings don't block a new proposal
    MappingFactory(customer=world.customer_a, integration_instance=inst, external_org_id="9", mapping_status="rejected")
    MappingFactory(customer=world.customer_b, integration_instance=inst, external_org_id="9")


def test_engineer_cannot_propose_mappings(world):
    inst = IntegrationFactory()
    resp = world.client(world.engineer_a).post(
        f"/api/v1/customers/{world.customer_a.id}/mappings/",
        {"integration_instance": str(inst.id), "external_org_id": "1"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------- integrations & SSRF (SEC-01)


@pytest.fixture
def allow_vsa_host(settings):
    settings.CONNECTOR_ALLOWED_HOSTS = {**settings.CONNECTOR_ALLOWED_HOSTS, "vsa_x": ["vsa.example.com"]}
    settings.CONNECTOR_APPROVED_PRIVATE_CIDRS = ["10.20.0.0/16"]


@pytest.mark.parametrize(
    "url",
    [
        "http://vsa.example.com",
        "https://169.254.169.254",
        "https://127.0.0.1",
        "https://[::1]",
        "https://user:pass@vsa.example.com",
        "https://vsa.example.com.evil.test",
        "https://evil.test",
        "https://vsa.example.com:8443",
        "https://vsa.example.com/api/v3",
        "https://vsa.example.com?x=1",
        "file:///etc/passwd",
        "https://10.99.0.5",
        "gopher://vsa.example.com",
    ],
)
def test_connector_url_policy_blocks_ssrf(world, allow_vsa_host, url):
    resp = world.client(world.super_admin).post(
        "/api/v1/integrations/", {"name": "x", "provider": "vsa_x", "base_url": url}
    )
    assert resp.status_code == 400, url
    assert not IntegrationInstance.objects.exists()


@pytest.mark.parametrize(
    ("url", "normalised"),
    [
        ("https://VSA.example.com/", "https://vsa.example.com"),
        ("https://10.20.1.5", "https://10.20.1.5"),
    ],
)
def test_connector_url_policy_allows_approved(world, allow_vsa_host, url, normalised):
    resp = world.client(world.super_admin).post(
        "/api/v1/integrations/",
        {"name": "VSA", "provider": "vsa_x", "base_url": url, "credential_ref": "vault:kv/portal/vsa"},
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["base_url"] == normalised
    assert "credential_ref" not in body and body["credential_configured"] is True
    assert body["verify_tls"] is True and body["enabled"] is False


def test_private_ip_only_for_vsa(world, allow_vsa_host):
    resp = world.client(world.super_admin).post(
        "/api/v1/integrations/", {"name": "IT", "provider": "itglue", "base_url": "https://10.20.1.5"}
    )
    assert resp.status_code == 400


def test_itglue_regional_hosts_allowed_by_default(world):
    resp = world.client(world.super_admin).post(
        "/api/v1/integrations/", {"name": "ITG EU", "provider": "itglue", "base_url": "https://api.eu.itglue.com"}
    )
    assert resp.status_code == 201


def test_fixture_instances_must_use_invalid_tld_and_no_credentials(world):
    client = world.client(world.super_admin)
    ok = client.post(
        "/api/v1/integrations/", {"name": "F", "provider": "vsa_x", "base_url": "https://f.invalid", "is_fixture": True}
    )
    assert ok.status_code == 201
    bad = client.post(
        "/api/v1/integrations/", {"name": "G", "provider": "vsa_x", "base_url": "https://evil.test", "is_fixture": True}
    )
    assert bad.status_code == 400
    bad2 = client.post(
        "/api/v1/integrations/",
        {
            "name": "H",
            "provider": "vsa_x",
            "base_url": "https://h.invalid",
            "is_fixture": True,
            "credential_ref": "vault:x",
        },
    )
    assert bad2.status_code == 400
    flip = client.patch(f"/api/v1/integrations/{ok.json()['id']}/", {"is_fixture": False})
    assert flip.status_code == 400


def test_tls_verification_cannot_be_disabled(world):
    resp = world.client(world.super_admin).post(
        "/api/v1/integrations/",
        {"name": "F", "provider": "vsa_x", "base_url": "https://f.invalid", "is_fixture": True, "verify_tls": False},
    )
    assert resp.json()["verify_tls"] is True
    inst = IntegrationInstance.objects.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        IntegrationInstance.objects.filter(pk=inst.pk).update(verify_tls=False)


def test_integrations_admin_only_and_options_scoped(world):
    IntegrationFactory()
    assert world.client(world.admin_a).get("/api/v1/integrations/").status_code == 403
    assert world.client(world.admin_a).get("/api/v1/integrations/options/").status_code == 200
    assert world.client(world.engineer_a).get("/api/v1/integrations/options/").status_code == 403
    assert world.client(world.super_admin).get("/api/v1/integrations/").status_code == 200


def test_integration_has_no_delete(world):
    inst = IntegrationFactory()
    assert world.client(world.super_admin).delete(f"/api/v1/integrations/{inst.id}/").status_code == 405
