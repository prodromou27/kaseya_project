"""P1-01 VSA X adapter contract tests. Fixture-based only — NOT live validation (TESTING.md VSA-01..05)."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
import requests

from apps.integrations.http import (
    EgressBlocked,
    EndpointNotAllowed,
    ReadOnlyHttpClient,
    VendorAuthError,
    VendorBadResponse,
    VendorRateLimited,
    VendorUnavailable,
    check_resolved_addresses,
)
from apps.integrations.models import IntegrationInstance
from apps.integrations.secrets import CredentialUnavailable, resolve_basic
from apps.integrations.vsa.adapter import ASSET_INCLUDE, VsaXAdapter, validate_org_id
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.integrations.vsa.schema import PageInvalid, RecordInvalid, normalize_asset, parse_page

FIXTURES = Path(__file__).parent / "fixtures" / "vsa_x"
DOC_EXAMPLE = json.loads((FIXTURES / "assets_doc_example.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.django_db


def make_assets(n: int, org: int = 7) -> list[dict]:
    return [
        {
            "Identifier": f"id-{i:05d}",
            "Name": f"HOST{i}",
            "OrganizationId": org,
            "SiteId": 1,
            "LastSeenOnline": "2026-11-01T10:00:00Z",
            "InstalledSoftware": [],
        }
        for i in range(n)
    ]


def fixture_instance(**kwargs) -> IntegrationInstance:
    return IntegrationInstance.objects.create(
        name=kwargs.pop("name", f"VSA fixture {uuid.uuid4().hex[:8]}"),
        provider="vsa_x",
        base_url="https://vsa.invalid",
        is_fixture=True,
        max_rps=20,
        **kwargs,
    )


def adapter_for(transport: FixtureVsaTransport, **kw) -> VsaXAdapter:
    return VsaXAdapter(fixture_instance(), transport=transport, sleeper=lambda s: None, **kw)


# ---------------------------------------------------------------- normalisation of the documented example


def test_documented_example_normalises_with_allowlisted_fields_only():
    page = parse_page(DOC_EXAMPLE)
    assert page.total_count == 1
    asset = normalize_asset(page.records[0])
    assert asset.identifier == "11111111-2222-3333-4444-555555555555"
    assert asset.organization_id == "6978" and asset.site_id == "6990" and asset.computer_id == "54759"
    assert asset.name == "Computer1" and asset.group_name == "Group1" and asset.device_type == "windows"
    assert asset.last_seen_online.isoformat() == "2017-08-11T15:10:06+00:00"
    assert asset.os_name == "Windows 10 Enterprise" and asset.os_version == "10.0.15063.0"
    assert asset.manufacturer == "VMware, Inc." and asset.serial_number.startswith("VMware-55")
    assert [(s.name, s.publisher, s.version) for s in asset.installed_software] == [
        ("Google Chrome", "Google Inc.", "60.0.3112.90"),
        ("Google Update Helper", "Google Inc.", "1.3.33.5"),
    ]
    dumped = repr(asset)
    for secret in ("XXXXX-XXXXX", "11111-22222-233333-44444", "ORG\\\\username", "John", "1.2.3.4"):
        assert secret not in dumped, secret


def test_missing_software_section_is_not_collected_not_empty():
    item = dict(DOC_EXAMPLE["Data"][0])
    del item["InstalledSoftware"]
    assert normalize_asset(item).installed_software is None
    item["InstalledSoftware"] = []
    assert normalize_asset(item).installed_software == ()


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda a: a.pop("Identifier"), "missing_identifier"),
        (lambda a: a.update(Identifier="  "), "missing_identifier"),
        (lambda a: a.pop("OrganizationId"), "missing_organization_id"),
        (lambda a: a.update(OrganizationId=True), "missing_organization_id"),
        (lambda a: a.update(LastSeenOnline="yesterday"), "invalid_timestamp"),
        (lambda a: a.update(LastSeenOnline="2026-01-01T00:00:00"), "timestamp_without_timezone"),
        (lambda a: a.update(InstalledSoftware="Chrome"), "invalid_installed_software"),
        (lambda a: a.update(Name={"nested": "object"}), "non_scalar_field"),
    ],
)
def test_malformed_records_are_rejected_individually(mutate, reason):
    item = json.loads(json.dumps(DOC_EXAMPLE["Data"][0]))
    mutate(item)
    with pytest.raises(RecordInvalid) as exc:
        normalize_asset(item)
    assert exc.value.reason == reason


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"Data": {}},
        {"Meta": {}},
        {"Data": [], "Meta": {"TotalCount": -1}},
        {"Data": [1], "Meta": {}},
        {"Data": [], "Meta": {"TotalCount": "5"}},
    ],
)
def test_malformed_pages_fail(body):
    with pytest.raises(PageInvalid):
        parse_page(body)


def test_long_text_is_truncated():
    item = json.loads(json.dumps(DOC_EXAMPLE["Data"][0]))
    item["Name"] = "A" * 5000
    assert len(normalize_asset(item).name) == 255


# ---------------------------------------------------------------- pagination (VSA-01)


@pytest.mark.parametrize("count", [0, 1, 99, 100, 101, 250])
def test_pagination_collects_all_unique_assets(count):
    transport = FixtureVsaTransport(make_assets(count) + make_assets(5, org=8))
    adapter = adapter_for(transport)
    pages = list(adapter.iter_asset_pages("7"))
    ids = [r["Identifier"] for p in pages for r in p.records]
    assert len(ids) == count == len(set(ids))
    assert all(p.total_count == count for p in pages)
    for path, params in transport.calls:
        assert path == "/api/v3/assets"
        assert params["$top"] == "100" and params["$filter"] == "OrganizationId eq 7"
        assert params["$orderby"] == "Identifier" and params["include"] == ASSET_INCLUDE
    assert [int(p["$skip"]) for _, p in transport.calls] == list(range(0, count // 100 * 100 + 1, 100))


def test_resume_from_checkpoint_skip():
    transport = FixtureVsaTransport(make_assets(250))
    pages = list(adapter_for(transport).iter_asset_pages("7", start_skip=200))
    assert transport.calls[0][1]["$skip"] == "200"
    assert sum(len(p.records) for p in pages) == 50


@pytest.mark.parametrize("bad", ["7 or 1 eq 1", "7)", "", "-1", "abc", "1" * 19])
def test_organization_id_must_be_integer_to_prevent_odata_injection(bad):
    with pytest.raises(ValueError):
        validate_org_id(bad)


# ---------------------------------------------------------------- rate limiting & failures (VSA-03/04)


def test_429_honours_retry_after_then_succeeds():
    sleeps: list[float] = []
    transport = FixtureVsaTransport(make_assets(3), scripted=[FakeResponse(429, headers={"Retry-After": "7"})])
    adapter = VsaXAdapter(fixture_instance(), transport=transport, sleeper=sleeps.append)
    pages = list(adapter.iter_asset_pages("7"))
    assert sum(len(p.records) for p in pages) == 3
    assert 7.0 in sleeps


def test_429_retries_are_bounded():
    transport = FixtureVsaTransport([], scripted=[FakeResponse(429, headers={"Retry-After": "1"})] * 10)
    with pytest.raises(VendorRateLimited):
        list(adapter_for(transport).iter_asset_pages("7"))
    assert len(transport.calls) == 5  # 1 + max_retries(4)


def test_excessive_retry_after_is_not_waited_out():
    transport = FixtureVsaTransport([], scripted=[FakeResponse(429, headers={"Retry-After": "3600"})])
    with pytest.raises(VendorRateLimited) as exc:
        list(adapter_for(transport).iter_asset_pages("7"))
    assert exc.value.retry_after == 3600 and len(transport.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_stops_immediately_without_retry(status):
    transport = FixtureVsaTransport([], scripted=[FakeResponse(status, body={"secret": "token-abc"})])
    with pytest.raises(VendorAuthError) as exc:
        list(adapter_for(transport).iter_asset_pages("7"))
    assert len(transport.calls) == 1
    assert "token-abc" not in str(exc.value)


def test_5xx_and_timeouts_retry_with_bounded_backoff():
    sleeps: list[float] = []
    transport = FixtureVsaTransport(
        make_assets(2), scripted=[FakeResponse(503), requests.Timeout("t"), FakeResponse(502)]
    )
    pages = list(VsaXAdapter(fixture_instance(), transport=transport, sleeper=sleeps.append).iter_asset_pages("7"))
    assert sum(len(p.records) for p in pages) == 2
    assert [x for x in sleeps if x >= 1] == [2, 4, 8]  # backoff (throttle sleeps are < 1s)

    transport = FixtureVsaTransport([], scripted=[FakeResponse(500)] * 10)
    with pytest.raises(VendorUnavailable):
        list(adapter_for(transport).iter_asset_pages("7"))


def test_non_json_and_redirects_fail_closed():
    transport = FixtureVsaTransport([], scripted=[FakeResponse(200, body=ValueError("not json"))])
    with pytest.raises(VendorBadResponse):
        list(adapter_for(transport).iter_asset_pages("7"))
    transport = FixtureVsaTransport([], scripted=[FakeResponse(302, headers={"Location": "http://169.254.169.254/"})])
    with pytest.raises(EgressBlocked):
        list(adapter_for(transport).iter_asset_pages("7"))


def test_throttle_respects_max_rps():
    sleeps: list[float] = []
    clock = iter([0.0, 0.0, 0.1, 0.1, 0.2, 0.2, 0.3, 0.3, 0.4, 0.4])
    inst = fixture_instance(name="slow")
    inst.max_rps = 2
    adapter = VsaXAdapter(
        inst, transport=FixtureVsaTransport(make_assets(250)), sleeper=sleeps.append, clock=lambda: next(clock)
    )
    list(adapter.iter_asset_pages("7"))
    assert sleeps and all(0 < s <= 0.5 for s in sleeps)


# ---------------------------------------------------------------- read-only allowlist & egress (SEC-01)


def test_client_has_no_write_methods_and_rejects_unlisted_paths():
    client = ReadOnlyHttpClient(
        base_url="https://vsa.invalid",
        provider="vsa_x",
        allowed_paths=[re.compile(r"/api/v3/assets")],
        auth=None,
        max_rps=10,
        transport=FixtureVsaTransport([]),
        is_fixture=True,
    )
    for name in ("post", "put", "patch", "delete", "request"):
        assert not hasattr(client, name)
    for path in (
        "/api/v3/automation/customfields/1/update",
        "/api/v3/devices/1/reboot",
        "/api/v3/assets/../x",
        "//evil",
        "api/v3/assets",
    ):
        with pytest.raises(EndpointNotAllowed):
            client.get_json(path)


def test_fixture_instance_cannot_use_network_transport():
    with pytest.raises(EgressBlocked):
        ReadOnlyHttpClient(
            base_url="https://vsa.invalid", provider="vsa_x", allowed_paths=[], auth=None, max_rps=1, is_fixture=True
        )


def test_live_instance_rechecks_allowlist_on_every_request(settings, monkeypatch):
    settings.CONNECTOR_ALLOWED_HOSTS = {**settings.CONNECTOR_ALLOWED_HOSTS, "vsa_x": ["vsa.example.com"]}
    monkeypatch.setenv("VSA_TOKEN", "id:secret")
    inst = IntegrationInstance.objects.create(
        name="live", provider="vsa_x", base_url="https://vsa.example.com", credential_ref="env:VSA_TOKEN"
    )
    transport = FixtureVsaTransport(make_assets(1))
    adapter = VsaXAdapter(inst, transport=transport, resolver=lambda h: ["93.184.215.14"], sleeper=lambda s: None)
    assert len(next(adapter.iter_asset_pages("7")).records) == 1
    settings.CONNECTOR_ALLOWED_HOSTS = {**settings.CONNECTOR_ALLOWED_HOSTS, "vsa_x": []}
    with pytest.raises(EgressBlocked):
        next(adapter.iter_asset_pages("7"))


@pytest.mark.parametrize(
    "addresses",
    [["169.254.169.254"], ["127.0.0.1"], ["10.0.0.5"], ["192.168.1.1"], ["203.0.113.10", "10.0.0.5"], ["::1"]],
)
def test_dns_resolution_to_internal_addresses_is_blocked(settings, addresses):
    settings.CONNECTOR_APPROVED_PRIVATE_CIDRS = []
    with pytest.raises(EgressBlocked):
        check_resolved_addresses("vsa.example.com", "vsa_x", lambda h: addresses)


def test_dns_resolution_to_approved_private_cidr_allowed_for_vsa(settings):
    settings.CONNECTOR_APPROVED_PRIVATE_CIDRS = ["10.20.0.0/16"]
    check_resolved_addresses("vsa.corp", "vsa_x", lambda h: ["10.20.1.5"])
    with pytest.raises(EgressBlocked):
        check_resolved_addresses("itg.corp", "itglue", lambda h: ["10.20.1.5"])


# ---------------------------------------------------------------- credentials


def test_credentials_resolved_from_reference_only(monkeypatch):
    monkeypatch.setenv("VSA_TOKEN", "token-id:token-secret")
    cred = resolve_basic("env:VSA_TOKEN")
    assert (cred.username, cred.password) == ("token-id", "token-secret")
    assert "token-secret" not in repr(cred)
    for ref in ("", "vault:x", "env:lower", "env:MISSING_VAR_X"):
        with pytest.raises(CredentialUnavailable):
            resolve_basic(ref)
    monkeypatch.setenv("BAD_TOKEN", "no-colon")
    with pytest.raises(CredentialUnavailable):
        resolve_basic("env:BAD_TOKEN")


def test_organizations_listing():
    transport = FixtureVsaTransport([], organizations=[{"Id": 1, "Name": "A", "Type": "Customer"}, {"Name": "no id"}])
    orgs, invalid = adapter_for(transport).list_organizations()
    assert [(o.id, o.name) for o in orgs] == [("1", "A")] and invalid == ["missing_id"]
