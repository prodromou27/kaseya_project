"""FLT-01: more device filters (hardware and identity, software and patching, several custom field rules).

Fixture-based (demo tenant), NOT live. Every expectation is computed independently from the stored rows, so the test
checks the filter, not the fixture's numbers.
"""

from __future__ import annotations

import pytest

from apps.inventory.models import AssetObservation, CustomFieldAllowlist, DeviceCustomField
from apps.inventory.queries import current_observations
from apps.patching.models import AppliedPolicyObservation, DeviceOsUpdate, PatchObservation
from apps.servers.models import ServerDesignation
from apps.software.models import ComplianceResult, SoftwareInstallation

from .test_automation import demo  # noqa: F401 - fixture

pytestmark = pytest.mark.django_db


def ids(world, user=None, **params) -> set[str]:
    resp = world.client(user or world.engineer_a).get(
        f"/api/v1/customers/{world.customer_a.id}/assets/", {**params, "page_size": 200}
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["count"] == len(body["results"])
    return {r["id"] for r in body["results"]}


def current(world) -> list[AssetObservation]:
    return list(current_observations(world.customer_a.id))


def with_policies(obs: list[AssetObservation]) -> None:
    """Every third device "Workstations - weekly", every third explicit none, the rest not collected."""
    for i, o in enumerate(obs):
        state, name = [("assigned", "Workstations - weekly"), ("explicit_none", "No Policy"), ("unknown", "")][i % 3]
        AppliedPolicyObservation.objects.update_or_create(
            observation=o,
            defaults={
                "customer": o.customer,
                "asset": o.asset,
                "generation": o.generation,
                "status": "collected" if state != "unknown" else "not_requested",
                "patch_state": state,
                "patch_policy_name": name,
            },
        )


def with_outdated(obs: list[AssetObservation]) -> set[str]:
    """A current evaluation per generation marking the first installation of every other device outdated."""
    from apps.software.models import ComplianceEvaluation

    marked: set[str] = set()
    for i, o in enumerate(obs):
        inst = SoftwareInstallation.objects.filter(observation=o).first()
        if inst is None or i % 2:
            continue
        ev = ComplianceEvaluation.objects.filter(generation=o.generation, is_current=True).first()
        if ev is None:
            ev = ComplianceEvaluation.objects.create(
                customer=o.customer,
                generation=o.generation,
                algorithm_version="t",
                catalog_fingerprint="t",
                is_current=True,
            )
        ComplianceResult.objects.update_or_create(
            evaluation=ev,
            installation=inst,
            defaults={"customer": o.customer, "asset": o.asset, "state": "outdated", "reason_code": "test"},
        )
        marked.add(str(o.asset_id))
    return marked


def test_hardware_and_identity(world, demo):  # noqa: F811
    obs = current(world)
    first = next(o for o in obs if o.manufacturer and o.model and o.os_version and o.client_version)
    assert ids(world, manufacturer=first.manufacturer.upper()) == {
        str(o.asset_id) for o in obs if o.manufacturer.casefold() == first.manufacturer.casefold()
    }
    part = first.model[: max(3, len(first.model) // 2)].lower()
    assert ids(world, model=part) == {str(o.asset_id) for o in obs if part in o.model.lower()}
    assert ids(world, os_version=first.os_version) == {str(o.asset_id) for o in obs if o.os_version == first.os_version}
    assert ids(world, agent_version=first.client_version) == {
        str(o.asset_id) for o in obs if o.client_version == first.client_version
    }
    assert ids(world, domain=first.domain) == {
        str(o.asset_id) for o in obs if o.domain.casefold() == first.domain.casefold()
    }
    tagged = next(o for o in obs if o.tags)
    assert ids(world, tag=tagged.tags[0]) == {str(o.asset_id) for o in obs if tagged.tags[0] in o.tags}
    facets = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/assets/facets/").json()
    assert first.manufacturer in facets["manufacturer"] and tagged.tags[0] in facets["tag"]
    assert first.client_version in facets["agent_version"]


def test_server_or_workstation_follows_the_servers_page_rule(world, demo):  # noqa: F811
    obs = current(world)
    detected = {str(o.asset_id) for o in obs if "server" in o.os_name.casefold()}
    assert detected and ids(world, role="server") == detected
    # Marking overrides detection either way.
    not_server = next(o for o in obs if str(o.asset_id) in detected)
    workstation = next(o for o in obs if str(o.asset_id) not in detected)
    ServerDesignation.objects.create(
        customer=world.customer_a, asset=not_server.asset, is_server=False, updated_by=world.admin_a
    )
    ServerDesignation.objects.create(
        customer=world.customer_a, asset=workstation.asset, is_server=True, updated_by=world.admin_a
    )
    expected = (detected - {str(not_server.asset_id)}) | {str(workstation.asset_id)}
    assert ids(world, role="server") == expected
    assert ids(world, role="workstation") == {str(o.asset_id) for o in obs} - expected


def test_installed_program_and_outdated_software(world, demo):  # noqa: F811
    obs = current(world)
    collected = {str(o.asset_id) for o in obs if o.software_status == "collected"}
    installs = SoftwareInstallation.objects.filter(observation__in=obs)
    name = installs.values_list("raw_name", flat=True).first()
    part = name[:6]
    having = {str(a) for a in installs.filter(raw_name__icontains=part).values_list("asset_id", flat=True)}
    assert having and ids(world, software=part) == having
    assert ids(world, software=part, software_presence="not_installed") == collected - having  # only collected devices
    with_outdated(obs)
    outdated = {
        str(a)
        for a in ComplianceResult.objects.filter(
            installation__observation__in=obs, evaluation__is_current=True, state="outdated"
        ).values_list("asset_id", flat=True)
    }
    assert outdated and ids(world, software_outdated="true") == outdated
    assert ids(world, software_outdated="false") == collected - outdated


def test_missing_os_updates_and_patch_policy(world, demo):  # noqa: F811
    obs = current(world)
    available = DeviceOsUpdate.objects.filter(patch_observation__observation__in=obs, state="available")
    critical = {str(a) for a in available.filter(severity="Critical").values_list("asset_id", flat=True)}
    anything = {str(a) for a in available.values_list("asset_id", flat=True)}
    assert critical and ids(world, missing_updates="critical") == critical
    assert ids(world, missing_updates="any") == anything
    read = {
        str(a)
        for a in PatchObservation.objects.filter(
            observation__in=obs, available_status__in=("collected", "carried_forward")
        ).values_list("asset_id", flat=True)
    }
    assert ids(world, missing_updates="none") == read - anything  # devices without update data are excluded
    with_policies(obs)
    facets = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/assets/facets/").json()
    assert facets["patch_policy"] == ["Workstations - weekly"]
    policies = AppliedPolicyObservation.objects.filter(observation__in=obs)
    name = policies.filter(patch_state="assigned").values_list("patch_policy_name", flat=True).first()
    assert ids(world, patch_policy=name.upper()) == {
        str(a)
        for a in policies.filter(patch_state="assigned", patch_policy_name=name).values_list("asset_id", flat=True)
    }
    assert ids(world, patch_policy="__none__") == {
        str(a)
        for a in policies.filter(patch_state__in=("explicit_none", "not_reported")).values_list("asset_id", flat=True)
    }


def test_several_custom_field_rules_must_all_match(world, demo):  # noqa: F811
    for name in ("Rack", "Asset Owner Department"):
        CustomFieldAllowlist.objects.create(
            customer=world.customer_a,
            name=name,
            name_key=name.casefold(),
            reason="filter test",
            state="approved",
            proposed_by=world.admin_a,
            reviewed_by=world.super_admin,
        )
    obs = current(world)
    # Store values directly (the sync budget is not under test here): every device gets both fields.
    from apps.inventory.models import DeviceDetailFetch

    for i, o in enumerate(obs):
        fetch, _ = DeviceDetailFetch.objects.update_or_create(
            observation=o,
            kind="custom_fields",
            defaults={"customer": o.customer, "asset": o.asset, "generation": o.generation, "status": "collected"},
        )
        DeviceCustomField.objects.create(
            fetch=fetch, customer=o.customer, asset=o.asset, generation=o.generation, name="Rack", value=f"R{i % 2}"
        )
        DeviceCustomField.objects.create(
            fetch=fetch,
            customer=o.customer,
            asset=o.asset,
            generation=o.generation,
            name="Asset Owner Department",
            value="TBD" if i % 3 == 0 else "Finance",
        )
    expected = {str(o.asset_id) for i, o in enumerate(obs) if i % 2 == 0 and i % 3 == 0}
    got = ids(
        world,
        custom_field="Rack",
        custom_field_state="equals",
        custom_field_value="R0",
        custom_field_2="Asset Owner Department",
        custom_field_state_2="equals",
        custom_field_value_2="TBD",
    )
    assert expected and got == expected
    # The third rule narrows further; an unapproved name in any rule is refused.
    assert ids(
        world,
        custom_field="Rack",
        custom_field_state="set",
        custom_field_3="Rack",
        custom_field_state_3="equals",
        custom_field_value_3="R1",
    ) == {str(o.asset_id) for i, o in enumerate(obs) if i % 2 == 1}
    bad = world.client(world.engineer_a).get(
        f"/api/v1/customers/{world.customer_a.id}/assets/", {"custom_field_2": "Owner"}
    )
    assert bad.status_code == 400 and "custom_field_2" in str(bad.json())


def test_filters_are_validated_and_work_for_jobs_and_exports(world, demo):  # noqa: F811
    url = f"/api/v1/customers/{world.customer_a.id}/assets/"
    eng = world.client(world.engineer_a)
    assert eng.get(url, {"software_presence": "installed"}).status_code == 400  # needs a program name
    assert eng.get(url, {"missing_updates": "some"}).status_code == 400
    assert eng.get(url, {"role": "laptop"}).status_code == 400
    # Saved views accept the new keys.
    resp = eng.post(
        f"/api/v1/customers/{world.customer_a.id}/saved-views/",
        {
            "name": "Critical servers",
            "view_type": "assets",
            "filters": {"role": "server", "missing_updates": "critical"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    # Another customer's devices never appear.
    other = world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_b.id}/assets/", {"role": "server"})
    assert other.status_code == 200 and other.json()["count"] == 0
