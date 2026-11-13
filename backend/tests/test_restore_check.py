"""VSAP-02 restore verification command."""

from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.integrations.vsa.fixtures import FixtureVsaTransport

from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db


def check() -> tuple[dict, bool]:
    out = io.StringIO()
    try:
        call_command("restore_check", stdout=out)
        ok = True
    except CommandError:
        ok = False
    return json.loads(out.getvalue()), ok


def test_clean_database_passes(world, env):  # noqa: F811
    run(env["ma"], world.engineer_a, FixtureVsaTransport([asset(1, 11, ip="10.0.1.10")]))
    report, ok = check()
    assert ok and report["ok"]
    assert report["checks"]["unapplied_migrations"]["value"] == []
    assert report["counts"]["assets"] == 1 and report["counts"]["active_super_admins"] == 1


def test_missing_integrity_trigger_fails(world):
    with connection.cursor() as cur:
        cur.execute("DROP TRIGGER audit_auditevent_no_update_delete ON audit_auditevent")
    report, ok = check()
    assert not ok and report["checks"]["integrity_triggers"]["missing"] == ["audit_auditevent_no_update_delete"]


def test_cross_customer_row_fails(world, env):  # noqa: F811
    run(env["ma"], world.engineer_a, FixtureVsaTransport([asset(1, 11, ip="10.0.1.10")]))
    with connection.cursor() as cur:  # simulate a corrupted/partial restore that bypassed the triggers
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # flush pending deferred FK events before ALTER TABLE
        cur.execute("ALTER TABLE inventory_assetobservation DISABLE TRIGGER USER")
        cur.execute("UPDATE inventory_assetobservation SET customer_id = %s", [world.customer_b.id])
        cur.execute("ALTER TABLE inventory_assetobservation ENABLE TRIGGER USER")
    report, ok = check()
    assert not ok
    assert report["checks"]["observation_customer_mismatch"] == {"ok": False, "value": 1}


def test_no_active_super_admin_fails(world):
    world.super_admin.is_active = False
    world.super_admin.save(update_fields=["is_active"])
    report, ok = check()
    assert not ok and report["checks"]["active_super_admin"]["ok"] is False
