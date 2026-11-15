"""vsa_probe: read-only, prints section/field names and counts, never values."""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationInstance

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo():
    return IntegrationInstance.objects.create(
        name="Demo probe", provider="vsa_x", base_url="https://vsa-demo.invalid", is_fixture=True, enabled=True
    )


def run(**kwargs) -> str:
    out = io.StringIO()
    call_command("vsa_probe", stdout=out, **kwargs)
    return out.getvalue()


def test_probe_reports_sections_without_values(demo):
    text = run(integration="Demo probe", org="1001", devices=3)
    assert "returned 3 device(s)" in text
    assert "InstalledSoftware  present 3/3" in text
    assert "Installed updates" in text and "Applied policies" in text
    # Names of fields only: no hostnames, software names or versions from the payload
    assert "DEMOA-" not in text and "Chrome" not in text and "Firefox" not in text
    assert AuditEvent.objects.filter(action="integration.probe", target_id=str(demo.id)).exists()


def test_probe_needs_an_unambiguous_integration_and_org(demo):
    with pytest.raises(CommandError):
        run(integration="Nope")
    with pytest.raises(CommandError, match="approved organisation mapping"):
        run(integration="Demo probe")


def test_probe_reports_a_missing_section(demo, monkeypatch):
    from apps.integrations.vsa import fixtures

    original = fixtures.FixtureVsaTransport.for_instance.__func__

    def without_software(cls, instance):
        transport = original(cls, instance)
        for asset in transport.assets:
            asset.pop("InstalledSoftware", None)
        return transport

    monkeypatch.setattr(fixtures.FixtureVsaTransport, "for_instance", classmethod(without_software))
    text = run(integration="Demo probe", org="1001", devices=2, no_details=True)
    assert "InstalledSoftware is missing on every sampled device" in text
