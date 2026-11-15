"""Third-party patch exposure: catalog version state x patch-rule coverage; configuration never shown as deployment."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.inventory.models import AssetObservation
from apps.inventory.queries import current_observations
from apps.patching.models import AppliedPolicyObservation, PatchPolicyDefinition
from apps.software.thirdparty import _rule_matches, normalise

from .test_p1_api import approve_chrome, reviewer, synced  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("rule", "install", "match"),
    [
        ("7-Zip (64-bit)", "7-Zip 24.08 (x64)", True),
        ("Google Chrome", "Google Chrome", True),
        ("Chrome", "Google Chrome", True),
        ("Google Chrome", "Google Chrome Beta", True),
        ("Firefox", "Google Chrome", False),
        ("", "Google Chrome", False),
    ],
)
def test_program_names_are_matched_after_normalising(rule, install, match):
    assert _rule_matches(normalise(rule), normalise(install)) is match


def attach_policies(world, with_rule_for: set[int]):
    """Even-index devices (by hostname) get policy 9 with a Chrome rule; odd ones get policy 8 without rules."""
    obs = sorted(current_observations(world.customer_a.id), key=lambda o: o.hostname)
    gen = obs[0].generation
    now = timezone.now()
    for pid, rules in (
        ("9", [{"ProductId": "chrome", "ProductName": "Google Chrome", "Action": "INSTALL_AND_UPDATE"}]),
        ("8", []),
    ):
        PatchPolicyDefinition.objects.create(
            customer=world.customer_a,
            generation=gen,
            policy_id=pid,
            status="collected",
            name=f"Policy {pid}",
            software_rules=rules,
            fetched_at=now,
        )
    for i, o in enumerate(obs):
        AppliedPolicyObservation.objects.update_or_create(
            observation=o,
            defaults={
                "customer": world.customer_a,
                "asset": o.asset,
                "generation": gen,
                "status": "collected",
                "collected_at": now,
                "patch_state": "assigned",
                "patch_policy_id": "9" if i in with_rule_for else "8",
            },
        )
    return obs


def test_outdated_installs_are_split_by_patch_rule_coverage(
    world,
    synced,  # noqa: F811
    reviewer,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    approve_chrome(world, reviewer, django_capture_on_commit_callbacks)
    attach_policies(world, with_rule_for={0, 1, 2})
    url = f"/api/v1/customers/{world.customer_a.id}/software/third-party/"
    body = world.client(world.viewer_a).get(url).json()
    assert "never shown as done" in body["disclaimer"]
    chrome = next(p for p in body["programs"] if p["program"] == "Google Chrome")
    assert chrome["installs"] == 6 and chrome["outdated"] == 3
    assert chrome["coverage"]["covered"] == 3 and chrome["coverage"]["not_covered"] == 3
    assert sum(chrome["outdated_coverage"].values()) == 3
    assert chrome["rule_actions"] == ["INSTALL_AND_UPDATE"]
    assert body["totals"]["outdated"] == 3
    assert body["totals"]["outdated_covered"] + body["totals"]["outdated_not_covered"] == 3
    # Uncatalogued software is never called outdated
    contoso = next(p for p in body["programs"] if p["program"] == "Contoso Tool")
    assert contoso["outdated"] == 0 and contoso["catalog_product"] is None

    devices = (
        world.client(world.viewer_a)
        .get(url + "devices/", {"program": chrome["program_key"], "coverage": "not_covered"})
        .json()
    )
    assert devices["count"] == 3 and all(r["policy_name"] == "Policy 8" for r in devices["results"])
    assert (
        world.client(world.viewer_a).get(url, {"outdated": "true"}).json()["programs"][0]["program"] == "Google Chrome"
    )


def test_devices_without_policy_data_are_unknown_not_uncovered(world, synced):  # noqa: F811
    body = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/software/third-party/").json()
    chrome = next(p for p in body["programs"] if p["program"] == "Google Chrome")
    assert chrome["coverage"] == {"covered": 0, "not_covered": 0, "no_policy": 0, "unknown": 6}


def test_explicit_no_policy_is_reported_as_no_policy(world, synced):  # noqa: F811
    obs = attach_policies(world, with_rule_for=set())
    AppliedPolicyObservation.objects.filter(observation=obs[0]).update(patch_state="explicit_none", patch_policy_id="")
    rows = (
        world.client(world.engineer_a)
        .get(f"/api/v1/customers/{world.customer_a.id}/software/third-party/devices/", {"coverage": "no_policy"})
        .json()
    )
    assert {r["hostname"] for r in rows["results"]} == {obs[0].hostname}


def test_other_customers_cannot_read_third_party_data(world, synced):  # noqa: F811
    url = f"/api/v1/customers/{world.customer_a.id}/software/third-party/"
    assert world.client(world.engineer_b).get(url).status_code == 404
    assert world.client(world.engineer_b).get(url + "devices/").status_code == 404
    assert AssetObservation.objects.exists()
