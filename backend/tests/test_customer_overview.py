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


def test_rows_are_cached_until_the_customers_data_changes(world, synced):  # noqa: F811
    """PERF-03: the second load reuses each customer's row; a new baseline (or sync) shows at once."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.compliance.models import ComplianceBaseline

    client = world.client(world.super_admin)
    with CaptureQueriesContext(connection) as first:
        client.get(URL)
    with CaptureQueriesContext(connection) as second:
        cached = client.get(URL).json()
    assert len(second.captured_queries) < len(first.captured_queries) / 2
    assert {r["code"]: r["baselines"] for r in cached["results"]} == {"ACME": 0, "BETA": 0}

    ComplianceBaseline.objects.create(
        customer=world.customer_a, name="Windows baseline", enabled=True, created_by=world.super_admin
    )
    fresh = {r["code"]: r["baselines"] for r in client.get(URL).json()["results"]}
    assert fresh == {"ACME": 1, "BETA": 0}
