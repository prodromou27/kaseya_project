"""Connect VSA wizard: the whole setup in two calls, without bypassing any control. No network: the connection test
and organisation discovery are stubbed (they are covered by their own suites)."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.customers.models import Customer, CustomerSourceMapping
from apps.integrations import views as integration_views
from apps.integrations.models import ConnectorHost, IntegrationInstance, SyncRun, SyncSchedule
from apps.integrations.secrets import resolve_instance_basic

pytestmark = pytest.mark.django_db
CONNECT = "/api/v1/integrations/connect/"
SECRET = "FAKE-WIZARD-SECRET-never-shown"
ORGS = [
    {"external_org_id": "101", "name": "Acme Holdings", "type": "", "mapping": None},
    {"external_org_id": "102", "name": "Beta & Co.", "type": "", "mapping": None},
]


@pytest.fixture
def stubs(settings, monkeypatch):
    settings.CONNECTOR_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.CONNECTOR_ALLOWED_HOSTS = {**settings.CONNECTOR_ALLOWED_HOSTS, "vsa_x": []}
    state = {"outcome": "ok"}
    monkeypatch.setattr(
        integration_views,
        "_test_connection",
        lambda inst: {"outcome": state["outcome"], "message": "stub", "data_basis": "live", "latency_ms": 1},
    )
    monkeypatch.setattr(integration_views, "_discover_organizations", lambda inst: Response({"organizations": ORGS}))
    return state


def _connect(client, **kw):
    body = {"base_url": "https://Tenant.vsax.example.com/", "token_id": "wizard-id", "token_secret": SECRET, **kw}
    return client.post(CONNECT, body, format="json")


def test_connect_sets_up_host_integration_credentials_and_lists_orgs(world, stubs):
    resp = _connect(world.client(world.super_admin))
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["connection"]["outcome"] == "ok" and [o["name"] for o in body["organizations"]] == [
        "Acme Holdings",
        "Beta & Co.",
    ]
    assert SECRET not in resp.content.decode()
    assert ConnectorHost.objects.get().hostname == "tenant.vsax.example.com"
    inst = IntegrationInstance.objects.get(pk=body["integration_id"])
    assert inst.base_url == "https://tenant.vsax.example.com" and not inst.enabled and inst.notifications_budget == 100
    assert resolve_instance_basic(inst).password == SECRET and inst.last_test_outcome == "ok"
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {
        "integration.host_allowed",
        "integration.created",
        "integration.credential_set",
        "integration.connection_test",
    } <= actions
    assert SECRET not in json.dumps(list(AuditEvent.objects.values_list("metadata", flat=True)))


def test_reconnecting_reuses_the_integration_and_replaces_credentials(world, stubs):
    client = world.client(world.super_admin)
    first = _connect(client).json()["integration_id"]
    second = _connect(client, token_secret="NEW-FAKE-SECRET").json()["integration_id"]
    assert first == second and IntegrationInstance.objects.count() == 1
    assert resolve_instance_basic(IntegrationInstance.objects.get()).password == "NEW-FAKE-SECRET"


def test_failed_connection_returns_no_orgs(world, stubs):
    stubs["outcome"] = "auth_failed"
    body = _connect(world.client(world.super_admin)).json()
    assert body["connection"]["outcome"] == "auth_failed" and body["organizations"] == []


@pytest.mark.parametrize(
    "url", ["http://vsa.example.com", "https://10.0.0.5", "https://vsa.corp.local", "https://localhost"]
)
def test_unsafe_urls_are_refused_before_anything_is_created(world, stubs, url):
    resp = _connect(world.client(world.super_admin), base_url=url)
    assert resp.status_code == 400
    assert not IntegrationInstance.objects.exists() and not ConnectorHost.objects.exists()


@pytest.mark.parametrize("who", ["admin_a", "engineer_a", "viewer_a"])
def test_only_super_admins(world, stubs, who):
    assert _connect(world.client(getattr(world, who))).status_code == 403


def test_import_creates_customers_mappings_schedules_and_starts_syncs(world, stubs):
    client = world.client(world.super_admin)
    iid = _connect(client).json()["integration_id"]
    picks = [
        {"external_org_id": "101", "name": "Acme Holdings"},
        {"external_org_id": "102", "name": "Beta & Co.", "customer_id": str(world.customer_b.id)},
    ]
    resp = client.post(f"/api/v1/integrations/{iid}/import-orgs/", {"organizations": picks}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert [i["customer"] for i in body["imported"]] == ["ACME-HOLDINGS", world.customer_b.code]
    assert body["syncs_started"] == 2 and all(i["sync"] == "started" for i in body["imported"])
    acme = Customer.objects.get(code="ACME-HOLDINGS")
    assert acme.name == "Acme Holdings" and acme.status == "active"
    mappings = CustomerSourceMapping.objects.filter(integration_instance_id=iid)
    assert {m.mapping_status for m in mappings} == {"approved"} and all(m.reviewed_by_id for m in mappings)
    assert SyncSchedule.objects.filter(mapping__in=mappings).count() == 2
    assert IntegrationInstance.objects.get(pk=iid).enabled
    assert SyncRun.objects.filter(mapping__in=mappings).count() == 2
    # Importing again does not duplicate anything.
    again = client.post(f"/api/v1/integrations/{iid}/import-orgs/", {"organizations": picks[:1]}, format="json").json()
    assert (
        again["imported"][0]["status"] == "already linked"
        and Customer.objects.filter(code__startswith="ACME-HOLDINGS").count() == 1
    )


def test_customer_codes_are_unique_and_valid(world, stubs):
    from apps.integrations.connect import _customer_code

    assert _customer_code("Beta & Co.", set()) == "BETA-CO"
    assert _customer_code("Beta & Co.", {"BETA-CO"}) == "BETA-CO-2"
    assert _customer_code("!", set()) == "CUSTOMER"
    assert _customer_code("é", set()) == "CUSTOMER"
