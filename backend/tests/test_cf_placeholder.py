"""CFA-10: placeholder custom field values ("TBD") for every device without a value, and filtering devices by a field.

Fixture-based, NOT live: the VSA X behaviour is the documented one simulated by the fixture tenant.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.customfields import jobs
from apps.customfields.models import AssignmentItem, AssignmentJob
from apps.integrations.vsa import fixtures
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.inventory.models import CustomFieldAllowlist, DeviceCustomField, DeviceDetailFetch

from .test_automation import demo  # noqa: F401 - fixture used by "ready"
from .test_custom_field_assignment import base, items, ready, ring, run_job, workstations  # noqa: F401
from .test_device_details import _assets, _budgets
from .test_vsa1_hierarchy_network import env, run  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    fixtures.FIXTURE_CUSTOM_FIELDS.clear()
    monkeypatch.setattr(jobs, "sleep", lambda s: None)
    yield
    fixtures.FIXTURE_CUSTOM_FIELDS.clear()


# ------------------------------------------------------------------------------------------------ device filter


@pytest.fixture
def racks(world, env):  # noqa: F811
    """Three devices with an approved "Rack" field: one "R1", one empty, one "TBD"; a fourth state: not read."""
    _budgets(env)
    CustomFieldAllowlist.objects.create(
        customer=world.customer_a,
        name="Rack",
        name_key="rack",
        reason="asset location",
        state="approved",
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
    )
    r = run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets()))
    rows = {c.asset.external_id: c for c in DeviceCustomField.objects.filter(generation_id=r.generation_id)}
    rows["11-dev-002"].value = ""
    rows["11-dev-002"].save()
    rows["11-dev-003"].value = "TBD"
    rows["11-dev-003"].save()
    return r


def hosts(world, user=None, **params):
    resp = world.client(user or world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/assets/", params)
    assert resp.status_code == 200, resp.content
    return sorted(r["external_id"] for r in resp.json()["results"])


def test_filter_devices_by_custom_field(world, racks):
    one, two, three = "11-dev-001", "11-dev-002", "11-dev-003"
    assert hosts(world, custom_field="Rack", custom_field_state="missing") == [two]
    assert hosts(world, custom_field="rack") == [two]  # default: empty; names match regardless of case
    assert hosts(world, custom_field="Rack", custom_field_state="set") == [one, three]
    assert hosts(world, custom_field="Rack", custom_field_state="equals", custom_field_value="tbd") == [three]
    assert hosts(world, custom_field="Rack", custom_field_state="not_equals", custom_field_value="TBD") == [one]
    assert hosts(world, custom_field="Rack", custom_field_state="missing_or_equals", custom_field_value="TBD") == [
        two,
        three,
    ]
    assert hosts(world, custom_field="Rack", custom_field_state="not_read") == []


def test_devices_whose_fields_were_not_read_are_never_reported_empty(world, racks):
    DeviceDetailFetch.objects.filter(
        generation_id=racks.generation_id, kind="custom_fields", asset__external_id="11-dev-002"
    ).update(status="failed")
    assert hosts(world, custom_field="Rack", custom_field_state="missing") == []
    assert hosts(world, custom_field="Rack", custom_field_state="not_read") == ["11-dev-002"]


def test_custom_field_filter_needs_an_approved_field_and_a_value(world, racks):
    url = f"/api/v1/customers/{world.customer_a.id}/assets/"
    eng = world.client(world.engineer_a)
    assert "custom_field" in str(eng.get(url, {"custom_field": "Owner"}).json())  # values not collected
    assert eng.get(url, {"custom_field": "Rack", "custom_field_state": "equals"}).status_code == 400
    assert eng.get(url, {"custom_field_state": "missing"}).status_code == 400
    # Another customer's approval does not open this customer's values.
    assert (
        world.client(world.engineer_b)
        .get(f"/api/v1/customers/{world.customer_b.id}/assets/", {"custom_field": "Rack"})
        .status_code
        == 400
    )


# ------------------------------------------------------------------------------------------------ fill empty only


class Adapter:
    """Device-level usage and effective values per device, as VSA X would report them."""

    def __init__(self, device_level: dict[str, str], effective: dict[str, str | None]):
        self.device_level, self.effective = device_level, effective

    def custom_field_device_usage(self, field_id, device=None, max_pages=100):
        return [{"ContextItemId": d, "Value": v} for d, v in self.device_level.items() if device in (None, d)]

    def device_custom_field_value(self, device, field_id):
        value = self.effective.get(device)
        return None if value is None else {"Id": field_id, "Value": value}


def _item() -> SimpleNamespace:
    return SimpleNamespace(
        device_external_id="d", current_value=None, current_source="", device_assigned=None, action_note=""
    )


@pytest.mark.parametrize(
    ("device_level", "effective", "action", "note"),
    [
        ({}, {}, "assign", ""),  # nothing anywhere: the placeholder is set
        ({"d": ""}, {}, "update", "Fills the empty value on this device"),
        ({"d": "Finance"}, {}, "skip", "Already has a value; left unchanged"),
        ({"d": "TBD"}, {}, "skip", "Already set on this device"),
        ({}, {"d": "Ring 2"}, "skip", "Has a value from the organisation, site or group; left unchanged"),
        ({}, {"d": "  "}, "assign", "Sets a device value; inherited values are unchanged"),
    ],
)
def test_fill_empty_only_changes_devices_without_a_value(device_level, effective, action, note):
    item = _item()
    field = SimpleNamespace(external_id="9", type="Text")
    jobs._classify(item, Adapter(device_level, effective), field, "TBD", None, only_if_empty=True)
    assert (item.action, item.action_note) == (action, note)


def test_without_fill_empty_existing_values_are_overwritten():
    item = _item()
    field = SimpleNamespace(external_id="9", type="Text")
    jobs._classify(item, Adapter({"d": "Finance"}, {}), field, "TBD", None, only_if_empty=False)
    assert item.action == "update" and item.action_note == "Overwrites the value set on this device"


def test_placeholder_for_all_devices_end_to_end(world, ready, django_capture_on_commit_callbacks):  # noqa: F811
    ws = workstations(world)
    iid = str(ready.id)
    empty, final = str(ws[1].asset.external_id), str(ws[2].asset.external_id)
    fixtures.FIXTURE_CUSTOM_FIELDS[(iid, "901", empty)] = ""  # assigned on the device, but empty
    fixtures.FIXTURE_CUSTOM_FIELDS[(iid, "901", final)] = "Ring 0"  # already has its final value
    admin = world.client(world.admin_a)
    body = run_job(
        world,
        admin,
        {"field": str(ring(world).id), "value": "TBD", "filters": {}, "only_if_empty": True},
        django_capture_on_commit_callbacks,
    )  # no overwrite acknowledgement needed: nothing is overwritten
    assert body["only_if_empty"] is True and body["state"] == "completed", body
    every = items(world, admin, body["id"], page_size=500)
    rows = {r["device_external_id"]: r for r in every if r["match_status"] == "matched"}
    assert len(rows) == len(ws)  # every workstation; servers are listed as unsupported and never changed
    assert {r["match_status"] for r in every if r["device_external_id"] not in rows} <= {"unsupported"}
    assert rows[empty]["action"] == "update" and rows[empty]["final_value"] == "TBD"
    assert rows[final]["action"] == "skip" and fixtures.FIXTURE_CUSTOM_FIELDS[(iid, "901", final)] == "Ring 0"
    # Every other device shows the organisation's "Ring 2" (or its own "Ring 1"): left unchanged.
    others = [r for d, r in rows.items() if d not in (empty, final)]
    assert others and all(r["action"] == "skip" for r in others)
    reasons = body["counts"]["not_changed"]  # shown when nothing is left to apply
    assert reasons["Has a value from the organisation, site or group; left unchanged"] > 0
    assert reasons["Already has a value; left unchanged"] >= 1
    # The next sync re-reads the written device only (so filters show "TBD" without waiting a week).
    from apps.inventory.models import Asset

    flagged = set(Asset.objects.exclude(details_refresh_requested_at=None).values_list("external_id", flat=True))
    assert flagged == {empty}
    written = {k[2]: v for k, v in fixtures.FIXTURE_CUSTOM_FIELDS.items()}
    assert written[empty] == "TBD" and sum(v == "TBD" for v in written.values()) == 1
    created = AssignmentJob.objects.get(pk=body["id"])
    from apps.audit.models import AuditEvent

    assert AuditEvent.objects.get(action="custom_field.job_created", target_id=str(created.id)).metadata[
        "only_if_empty"
    ]


def test_value_set_after_the_preview_is_not_overwritten(world, ready, django_capture_on_commit_callbacks):  # noqa: F811
    device = workstations(world)[1]
    iid, did = str(ready.id), str(device.asset.external_id)
    fixtures.FIXTURE_CUSTOM_FIELDS[(iid, "901", did)] = ""
    admin = world.client(world.admin_a)
    job = admin.post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "TBD", "assets": [str(device.asset_id)], "only_if_empty": True},
        format="json",
    ).json()
    with django_capture_on_commit_callbacks(execute=True):
        admin.post(f"{base(world)}/custom-field-jobs/{job['id']}/preview/")
    fixtures.FIXTURE_CUSTOM_FIELDS[(iid, "901", did)] = "Ring 0"  # someone sets the final value meanwhile
    with django_capture_on_commit_callbacks(execute=True):
        assert admin.post(f"{base(world)}/custom-field-jobs/{job['id']}/confirm/", {"confirm": True}, format="json")
    item = AssignmentItem.objects.get(job_id=job["id"])
    assert item.result == "skipped" and fixtures.FIXTURE_CUSTOM_FIELDS[(iid, "901", did)] == "Ring 0"


def test_fill_empty_needs_one_value(world, ready):  # noqa: F811
    resp = world.client(world.admin_a).post(
        f"{base(world)}/custom-field-jobs/",
        {"field": str(ring(world).id), "value": "", "filters": {}, "only_if_empty": True},
        format="json",
    )
    assert resp.status_code == 400
