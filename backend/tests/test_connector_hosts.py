"""Connector egress allowlist managed in the portal by super admins (fixture/fake hostnames only, no network)."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.integrations.http import EgressBlocked
from apps.integrations.models import ConnectorHost, IntegrationInstance
from apps.integrations.vsa.adapter import VsaXAdapter
from apps.integrations.vsa.fixtures import FixtureVsaTransport

pytestmark = pytest.mark.django_db
HOSTS = "/api/v1/connector-hosts/"


@pytest.fixture(autouse=True)
def no_deployment_hosts(settings):
    settings.CONNECTOR_ALLOWED_HOSTS = {**settings.CONNECTOR_ALLOWED_HOSTS, "vsa_x": []}
    settings.CONNECTOR_APPROVED_PRIVATE_CIDRS = []


def _add(client, hostname, **extra):
    return client.post(HOSTS, {"provider": "vsa_x", "hostname": hostname, **extra}, format="json")


def _integration(client, url="https://vsa.example.com"):
    return client.post("/api/v1/integrations/", {"name": "VSA", "provider": "vsa_x", "base_url": url}, format="json")


def test_super_admin_allows_host_then_creates_integration(world):
    client = world.client(world.super_admin)
    refused = _integration(client)
    assert refused.status_code == 400 and "Allowed API hosts" in refused.content.decode()
    resp = _add(client, "  HTTPS://VSA.Example.com/ ", reason="pilot tenant")
    assert resp.status_code == 201, resp.content
    assert resp.json()["hostname"] == "vsa.example.com" and resp.json()["added_by"] == world.super_admin.email
    assert _integration(client).status_code == 201
    ev = AuditEvent.objects.get(action="integration.host_allowed")
    assert ev.metadata["hostname"] == "vsa.example.com" and ev.metadata["reason"] == "pilot tenant"
    listed = client.get(HOSTS).json()
    assert [r["hostname"] for r in listed["results"]] == ["vsa.example.com"] and not [
        d for d in listed["deployment"] if d["provider"] == "vsa_x"
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "*.example.com",
        "10.0.0.5",
        "169.254.169.254",
        "localhost",
        "vsa.corp.local",
        "vsa.example.internal",
        "vsa.example.com:8443",
        "vsa.example.com/api",
        "user@vsa.example.com",
        "com",
        "a..example.com",
        "",
    ],
)
def test_unsafe_or_malformed_hosts_refused(world, bad):
    resp = _add(world.client(world.super_admin), bad)
    assert resp.status_code == 400, (bad, resp.content)
    assert not ConnectorHost.objects.exists()


def test_duplicate_and_other_providers_refused(world):
    client = world.client(world.super_admin)
    assert _add(client, "vsa.example.com").status_code == 201
    assert _add(client, "VSA.example.com").status_code == 400
    assert client.post(HOSTS, {"provider": "itglue", "hostname": "x.example.com"}, format="json").status_code == 400


@pytest.mark.parametrize("who", ["admin_a", "engineer_a", "viewer_a", "outsider"])
def test_only_super_admin(world, who):
    client = world.client(getattr(world, who))
    assert client.get(HOSTS).status_code == 403
    assert _add(client, "vsa.example.com").status_code == 403
    assert not ConnectorHost.objects.exists()


def test_removing_host_in_use_is_refused_until_integration_changes(world):
    client = world.client(world.super_admin)
    host_id = _add(client, "vsa.example.com").json()["id"]
    _add(client, "vsa2.example.com")
    inst_id = _integration(client).json()["id"]
    resp = client.delete(f"{HOSTS}{host_id}/")
    assert resp.status_code == 400 and "Still used by: VSA" in resp.content.decode()
    client.patch(f"/api/v1/integrations/{inst_id}/", {"base_url": "https://vsa2.example.com"}, format="json")
    assert client.delete(f"{HOSTS}{host_id}/").status_code == 204
    assert AuditEvent.objects.filter(action="integration.host_removed", metadata__hostname="vsa.example.com").exists()


def test_connector_rechecks_portal_allowlist_on_every_request(world):
    client = world.client(world.super_admin)
    _add(client, "vsa.example.com")
    inst = IntegrationInstance.objects.get(pk=_integration(client).json()["id"])
    adapter = VsaXAdapter.__new__(VsaXAdapter)  # build the client without a credential
    from apps.integrations.http import ReadOnlyHttpClient
    from apps.integrations.vsa.adapter import ALLOWED_PATHS

    adapter.client = ReadOnlyHttpClient(
        base_url=inst.base_url,
        provider="vsa_x",
        allowed_paths=ALLOWED_PATHS,
        auth=None,
        max_rps=20,
        transport=FixtureVsaTransport([]),
        is_fixture=False,
        resolver=lambda h: ["93.184.215.14"],
        sleeper=lambda s: None,
    )
    adapter.instance = inst
    list(adapter.iter_asset_pages("7"))
    ConnectorHost.objects.all().delete()  # e.g. removed directly, bypassing the in-use check
    with pytest.raises(EgressBlocked):
        list(adapter.iter_asset_pages("7"))


def test_private_resolution_still_blocked_for_portal_hosts(world):
    from apps.integrations.http import check_resolved_addresses

    _add(world.client(world.super_admin), "vsa.example.com")
    with pytest.raises(EgressBlocked):
        check_resolved_addresses("vsa.example.com", "vsa_x", lambda h: ["10.0.0.5"])
