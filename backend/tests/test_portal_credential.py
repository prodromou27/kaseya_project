"""VSA X API token entered by a super admin in the portal: encrypted at rest, write-only, audited.

Fixture/fake values only: no real token and no live VSA call.
"""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from django.db import connection

from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import CredentialUnavailable, resolve_instance_basic
from apps.integrations.vsa.adapter import VsaXAdapter
from apps.integrations.vsa.fixtures import FixtureVsaTransport

pytestmark = pytest.mark.django_db
TOKEN_ID, TOKEN_SECRET = "fake-token-id-123", "FAKE-SECRET-value-never-shown"
PAYLOAD = {"fields": {"token_id": TOKEN_ID, "token_secret": TOKEN_SECRET}}


@pytest.fixture
def key(settings):
    settings.CONNECTOR_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.CONNECTOR_ALLOWED_HOSTS = {
        **settings.CONNECTOR_ALLOWED_HOSTS,
        "vsa_x": ["vsa.example.com", "vsa2.example.com"],
    }
    return settings


@pytest.fixture
def live(key):
    return IntegrationInstance.objects.create(name="VSA live", provider="vsa_x", base_url="https://vsa.example.com")


def _url(inst):
    return f"/api/v1/integrations/{inst.id}/credential/"


def test_super_admin_sets_token_encrypted_and_never_returned(world, live):
    client = world.client(world.super_admin)
    resp = client.post(_url(live), PAYLOAD, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["credential_configured"] is True and body["credential_source"] == "portal"
    assert body["credential_set_by"] == world.super_admin.email and body["credential_set_at"]
    assert TOKEN_SECRET not in resp.content.decode() and TOKEN_ID not in resp.content.decode()
    listed = client.get("/api/v1/integrations/").content.decode()
    assert TOKEN_SECRET not in listed and "credential_ciphertext" not in listed

    # At rest: only ciphertext, in no column in plaintext.
    with connection.cursor() as cur:
        cur.execute("SELECT row_to_json(i)::text FROM integrations_integrationinstance i WHERE id = %s", [live.id])
        row = cur.fetchone()[0]
    assert TOKEN_SECRET not in row and TOKEN_ID not in row
    live.refresh_from_db()
    cred = resolve_instance_basic(live)
    assert (cred.username, cred.password) == (TOKEN_ID, TOKEN_SECRET)

    ev = AuditEvent.objects.get(action="integration.credential_set")
    assert ev.outcome == "success" and ev.metadata == {"replaced": False, "server_reference_also_set": False}
    assert TOKEN_SECRET not in json.dumps(ev.metadata)


def test_adapter_uses_portal_token_as_basic_auth(world, live):
    world.client(world.super_admin).post(_url(live), PAYLOAD, format="json")
    live.refresh_from_db()
    seen = []

    class Capture(FixtureVsaTransport):
        def get(self, url, *, params, headers, auth):
            seen.append(auth)
            return super().get(url, params=params, headers=headers, auth=auth)

    adapter = VsaXAdapter(live, transport=Capture([]), resolver=lambda h: ["93.184.215.14"], sleeper=lambda s: None)
    list(adapter.iter_asset_pages("7"))
    assert seen and seen[0] == (TOKEN_ID, TOKEN_SECRET)


def test_portal_token_takes_precedence_over_server_reference(world, key, monkeypatch):
    monkeypatch.setenv("VSA_TOKEN", "server-id:server-secret")
    inst = IntegrationInstance.objects.create(
        name="both", provider="vsa_x", base_url="https://vsa.example.com", credential_ref="env:VSA_TOKEN"
    )
    assert resolve_instance_basic(inst).username == "server-id"
    world.client(world.super_admin).post(_url(inst), PAYLOAD, format="json")
    inst.refresh_from_db()
    assert resolve_instance_basic(inst).username == TOKEN_ID
    assert AuditEvent.objects.get(action="integration.credential_set").metadata["server_reference_also_set"] is True


@pytest.mark.parametrize("who", ["admin_a", "engineer_a", "viewer_a", "outsider"])
def test_only_super_admin_may_set_or_clear(world, live, who):
    client = world.client(getattr(world, who))
    assert client.post(_url(live), PAYLOAD, format="json").status_code == 403
    assert client.delete(_url(live)).status_code == 403
    live.refresh_from_db()
    assert live.credential_ciphertext == ""


def test_anonymous_refused(live):
    from rest_framework.test import APIClient

    assert APIClient().post(_url(live), PAYLOAD, format="json").status_code in (401, 403)


@pytest.mark.parametrize(
    "payload",
    [
        {"token_id": "has:colon", "token_secret": "x"},
        {"token_id": "has space", "token_secret": "x"},
        {"token_id": "ok", "token_secret": "has space"},
        {"token_id": "", "token_secret": "x"},
        {"token_id": "ok"},
        {"token_id": "ok", "token_secret": "x", "extra_field": "sneaky-value"},
    ],
)
def test_malformed_token_refused_without_echo(world, live, payload):
    resp = world.client(world.super_admin).post(_url(live), {"fields": payload}, format="json")
    assert resp.status_code == 400
    for value in payload.values():
        if len(value) > 2:
            assert value not in resp.content.decode()


def test_fixture_instance_refuses_credentials(world, key):
    fx = IntegrationInstance.objects.create(
        name="fx", provider="vsa_x", base_url="https://vsa.invalid", is_fixture=True
    )
    resp = world.client(world.super_admin).post(_url(fx), PAYLOAD, format="json")
    assert resp.status_code == 400 and "Fixture" in resp.json()["error"]["message"] + json.dumps(resp.json())


def test_without_encryption_key_storage_is_refused(world, settings):
    settings.CONNECTOR_ENCRYPTION_KEY = ""
    settings.CONNECTOR_ALLOWED_HOSTS = {**settings.CONNECTOR_ALLOWED_HOSTS, "vsa_x": ["vsa.example.com"]}
    inst = IntegrationInstance.objects.create(name="nokey", provider="vsa_x", base_url="https://vsa.example.com")
    client = world.client(world.super_admin)
    assert client.get("/api/v1/integrations/credential-storage/").json() == {"available": False}
    resp = client.post(_url(inst), PAYLOAD, format="json")
    assert resp.status_code == 400 and "CONNECTOR_ENCRYPTION_KEY" in resp.content.decode()


def test_changed_key_or_copied_ciphertext_fails_safely(world, live, key):
    world.client(world.super_admin).post(_url(live), PAYLOAD, format="json")
    live.refresh_from_db()
    other = IntegrationInstance.objects.create(name="other", provider="vsa_x", base_url="https://vsa2.example.com")
    other.credential_ciphertext = live.credential_ciphertext  # copied row value (e.g. SQL tampering)
    with pytest.raises(CredentialUnavailable, match="do not belong"):
        resolve_instance_basic(other)
    old = key.CONNECTOR_ENCRYPTION_KEY
    key.CONNECTOR_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(CredentialUnavailable, match="cannot be decrypted") as exc:
        resolve_instance_basic(live)
    assert TOKEN_SECRET not in str(exc.value)
    key.CONNECTOR_ENCRYPTION_KEY = f"{key.CONNECTOR_ENCRYPTION_KEY},{old}"  # rotation: old key still decrypts
    assert resolve_instance_basic(live).password == TOKEN_SECRET


def test_changing_base_url_clears_portal_token(world, live):
    client = world.client(world.super_admin)
    client.post(_url(live), PAYLOAD, format="json")
    resp = client.patch(f"/api/v1/integrations/{live.id}/", {"base_url": "https://vsa2.example.com"}, format="json")
    assert resp.status_code == 200 and resp.json()["credential_source"] == "none"
    assert AuditEvent.objects.filter(
        action="integration.credential_cleared", metadata__reason="base_url_changed"
    ).exists()
    # Other edits keep it.
    client.post(_url(live), PAYLOAD, format="json")
    assert (
        client.patch(f"/api/v1/integrations/{live.id}/", {"enabled": True}, format="json").json()["credential_source"]
        == "portal"
    )


def test_remove_token(world, live):
    client = world.client(world.super_admin)
    client.post(_url(live), PAYLOAD, format="json")
    resp = client.delete(_url(live))
    assert resp.status_code == 200 and resp.json()["credential_configured"] is False
    live.refresh_from_db()
    assert live.credential_ciphertext == "" and live.credential_set_by is None
    with pytest.raises(CredentialUnavailable):
        resolve_instance_basic(live)
    assert AuditEvent.objects.filter(action="integration.credential_cleared", metadata__reason="admin_removed").exists()


def test_connection_test_with_portal_token_and_reset_after_change(world, live, monkeypatch):
    client = world.client(world.super_admin)
    live.last_test_outcome = "ok"
    live.save(update_fields=["last_test_outcome"])
    client.post(_url(live), PAYLOAD, format="json")
    live.refresh_from_db()
    assert live.last_test_outcome == ""  # old test result no longer describes the new token


def test_providers_catalog_lists_available_and_planned(world):
    body = world.client(world.super_admin).get("/api/v1/integrations/providers/").json()
    by_key = {p["key"]: p for p in body}
    assert by_key["vsa_x"]["implemented"] is True
    assert [f["name"] for f in by_key["vsa_x"]["fields"]] == ["token_id", "token_secret"]
    assert by_key["vsa_x"]["fields"][1]["secret"] is True
    assert {"itglue", "autotask", "tenable"} <= set(by_key) and not by_key["itglue"]["implemented"]
    assert all("pattern" not in f for p in body for f in p["fields"])  # regexes stay server-side
    assert world.client(world.engineer_a).get("/api/v1/integrations/providers/").status_code == 403


def test_planned_provider_never_stores_credentials(world, key):
    inst = IntegrationInstance.objects.create(name="itg", provider="itglue", base_url="https://api.itglue.com")
    resp = world.client(world.super_admin).post(_url(inst), {"fields": {"api_key": "FAKE-ITG-KEY"}}, format="json")
    assert resp.status_code == 400 and "not available yet" in resp.content.decode()
    inst.refresh_from_db()
    assert inst.credential_ciphertext == ""


def test_all_fields_are_inside_one_encrypted_blob_bound_to_provider(world, live):
    from apps.integrations.secrets import _cipher, decrypt_fields

    world.client(world.super_admin).post(_url(live), PAYLOAD, format="json")
    live.refresh_from_db()
    plaintext = json.loads(_cipher().decrypt(live.credential_ciphertext.encode()))
    assert plaintext["provider"] == "vsa_x"
    assert plaintext["fields"] == {"token_id": TOKEN_ID, "token_secret": TOKEN_SECRET}
    live.provider = "itglue"  # same row, different provider: refused
    with pytest.raises(CredentialUnavailable, match="do not belong"):
        decrypt_fields(live)


def test_v1_ciphertext_from_first_release_still_decrypts(world, live):
    from apps.integrations.secrets import _cipher

    v1_plaintext = f"{live.id}\n{TOKEN_ID}:{TOKEN_SECRET}"
    live.credential_ciphertext = _cipher().encrypt(v1_plaintext.encode()).decode()
    cred = resolve_instance_basic(live)
    assert (cred.username, cred.password) == (TOKEN_ID, TOKEN_SECRET)
