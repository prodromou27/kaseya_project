"""CRM-05 all-customers overview: only readable customers, figures equal to each customer's own summaries."""

from __future__ import annotations

import pytest

from .test_p1_api import synced  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/customers/overview/"


def test_super_admin_sees_every_customer_side_by_side(world, synced):  # noqa: F811
    body = world.client(world.super_admin).get(URL).json()
    rows = {r["code"]: r for r in body["results"]}
    assert set(rows) == {"ACME", "BETA"} and body["truncated"] is False
    assert rows["ACME"]["devices"] == 6 and rows["BETA"]["devices"] == 4
    health = (
        world.client(world.super_admin).get(f"/api/v1/customers/{world.customer_a.id}/device-health/summary/").json()
    )
    assert rows["ACME"]["devices"] == health["devices"]
    assert rows["ACME"]["compliance_pct"] is None and rows["ACME"]["baselines"] == 0
    assert rows["ACME"]["as_of"] and rows["ACME"]["stale"] is False


def test_members_only_see_their_own_customers(world, synced):  # noqa: F811
    assert [r["code"] for r in world.client(world.engineer_a).get(URL).json()["results"]] == ["ACME"]
    assert [r["code"] for r in world.client(world.engineer_b).get(URL).json()["results"]] == ["BETA"]
    assert world.client(world.outsider).get(URL).json()["results"] == []
