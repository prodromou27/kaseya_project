"""Custom field writes set up in the portal by a super admin: separate write token (encrypted, write-only, audited),
test-workstation route validation, and the server switch as an emergency stop. Fake tokens and fixture VSA only."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from django.db import connection

from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import (
    CredentialUnavailable,
    decrypt_fields,
    has_write_credential,
    resolve_instance_basic,
    resolve_instance_write,
)
from apps.integrations.vsa import fixtures
from apps.integrations.vsa.cf_writer import VsaCustomFieldWriter, WriteNotAvailable, availability
from apps.inventory.queries import current_observations

from .test_automation import demo  # noqa: F401

pytestmark = pytest.mark.django_db
WRITE_ID, WRITE_SECRET = "fake-write-id-9", "FAKE-WRITE-secret-never-shown"
READ = {"fields": {"token_id": "fake-read-id-1", "token_secret": "FAKE-READ-secret"}}


@pytest.fixture
def live(settings):
    settings.CONNECTOR_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.CONNECTOR_ALLOWED_HOSTS = {
        **settings.CONNECTOR_ALLOWED_HOSTS,
        "vsa_x": ["vsa.example.com", "vsa2.example.com"],
    }
    return IntegrationInstance.objects.create(
        name="VSA live", provider="vsa_x", base_url="https://vsa.example.com", enabled=True
    )


def _url(inst, action="write-credential"):
    return f"/api/v1/integrations/{inst.id}/{action}/"


def test_super_admin_enters_write_token_encrypted_and_separate(world, live):
    client = world.client(world.super_admin)
    assert client.post(_url(live, "credential"), READ, format="json").status_code == 200
    same = client.post(_url(live), {"token_id": "fake-read-id-1", "token_secret": "x"}, format="json")
    assert same.status_code == 400 and "not the read token" in same.content.decode()

    resp = client.post(_url(live), {"token_id": WRITE_ID, "token_secret": WRITE_SECRET}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["write_credential_configured"] and body["write_credential_source"] == "portal"
    assert body["write_credential_set_by"] == world.super_admin.email
    assert WRITE_SECRET not in resp.content.decode() and WRITE_ID not in resp.content.decode()
    with connection.cursor() as cur:
        cur.execute("SELECT row_to_json(i)::text FROM integrations_integrationinstance i WHERE id = %s", [live.id])
        row = cur.fetchone()[0]
    assert WRITE_SECRET not in row and WRITE_ID not in row
    live.refresh_from_db()
    assert has_write_credential(live)
    cred = resolve_instance_write(live)
    assert (cred.username, cred.password) == (WRITE_ID, WRITE_SECRET)
    assert resolve_instance_basic(live).username == "fake-read-id-1"  # the read token is unchanged

    # Purpose-bound: the write blob is never accepted as the read credential, nor the read blob as the write token.
    read_blob, write_blob = live.credential_ciphertext, live.write_credential_ciphertext
    live.credential_ciphertext = write_blob
    with pytest.raises(CredentialUnavailable):
        decrypt_fields(live)
    live.credential_ciphertext, live.write_credential_ciphertext = read_blob, read_blob
    with pytest.raises(CredentialUnavailable):
        resolve_instance_write(live)
    live.refresh_from_db()

    ev = AuditEvent.objects.get(action="integration.write_credential_set")
    assert WRITE_SECRET not in json.dumps(ev.metadata) and WRITE_ID not in json.dumps(ev.metadata)

    # Used by the custom field writer as Basic auth (never the read token).
    live.custom_field_writes_enabled, live.custom_field_write_route = True, "customfields"
    live.save()
    assert availability(live) == (True, "")
    assert VsaCustomFieldWriter(live, transport=object()).auth == (WRITE_ID, WRITE_SECRET)

    # A new server address clears it; removing it is audited.
    assert client.patch(f"/api/v1/integrations/{live.id}/", {"base_url": "https://vsa2.example.com"}, format="json")
    live.refresh_from_db()
    assert not live.write_credential_ciphertext and not live.custom_field_write_route
    assert AuditEvent.objects.filter(action="integration.write_credential_cleared").exists()
    with pytest.raises(WriteNotAvailable):
        VsaCustomFieldWriter(live)


def test_only_super_admins_set_up_writes(world, live):
    payload = {"token_id": WRITE_ID, "token_secret": WRITE_SECRET}
    for user in (world.admin_a, world.engineer_a, world.viewer_a):
        client = world.client(user)
        assert client.post(_url(live), payload, format="json").status_code == 403
        assert client.delete(_url(live)).status_code == 403
        assert (
            client.post(
                _url(live, "validate-custom-field-route"),
                {"device": "x", "field_id": "901", "value": "v", "confirm_test_device": True},
                format="json",
            ).status_code
            == 403
        )
    live.refresh_from_db()
    assert not live.write_credential_ciphertext


def test_route_validation_in_the_portal_writes_once_and_records_the_route(world, demo, settings):  # noqa: F811
    fixtures.FIXTURE_CUSTOM_FIELDS.clear()
    settings.VSA_CUSTOM_FIELD_WRITES_ENABLED = True
    client = world.client(world.super_admin)
    ws = next(o for o in current_observations(world.customer_a.id) if "server" not in o.os_name.casefold())
    url = _url(demo, "validate-custom-field-route")
    body = {"device": ws.hostname.lower(), "field_id": "901", "value": "Ring test", "confirm_test_device": False}
    assert client.post(url, body, format="json").status_code == 400  # must confirm it is a test device
    body["confirm_test_device"] = True
    assert (
        "not in this integration" in client.post(url, {**body, "device": "NO-SUCH-PC"}, format="json").content.decode()
    )
    resp = client.post(url, body, format="json")
    assert resp.status_code == 200, resp.content
    result = resp.json()["result"]
    assert result["route"] == "customfields" and result["device"] == str(ws.asset.external_id)
    assert resp.json()["integration"]["custom_field_write_route"] == "customfields"
    # Exactly one device was written.
    assert list(fixtures.FIXTURE_CUSTOM_FIELDS.items()) == [
        ((str(demo.id), "901", str(ws.asset.external_id)), "Ring test")
    ]
    ev = AuditEvent.objects.get(action="custom_field.route_validated")
    assert ev.actor == world.super_admin and ev.metadata["route"] == "customfields"

    # The server switch is an emergency stop.
    settings.VSA_CUSTOM_FIELD_WRITES_ENABLED = False
    stopped = client.post(url, body, format="json")
    assert stopped.status_code == 400 and "emergency stop" in stopped.content.decode()
    fixtures.FIXTURE_CUSTOM_FIELDS.clear()
