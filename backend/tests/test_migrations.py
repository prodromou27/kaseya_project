"""P0-03 AC: migrations run forward and backward on real PostgreSQL."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

PROJECT_APPS = ["accounts", "customers", "integrations", "audit", "reporting"]


def _tables() -> set[str]:
    return set(connection.introspection.table_names())


@pytest.mark.django_db(transaction=True)
def test_database_is_postgresql():
    assert connection.vendor == "postgresql"
    with connection.cursor() as cur:
        cur.execute("SHOW server_version_num")
        assert int(cur.fetchone()[0]) >= 160000, "PostgreSQL 16+ required"


@pytest.mark.django_db(transaction=True)
def test_migrations_down_and_up():
    try:
        call_command("migrate", "accounts", "zero", verbosity=0)  # cascades to customers/audit/reporting
        call_command("migrate", "integrations", "zero", verbosity=0)
        remaining = {t for t in _tables() if t.split("_")[0] in PROJECT_APPS}
        assert remaining == set(), remaining
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_proc WHERE proname = 'audit_auditevent_append_only'")
            assert cur.fetchone()[0] == 0
    finally:
        call_command("migrate", verbosity=0)
    assert {"accounts_user", "customers_customer", "audit_auditevent", "reporting_reportrun"} <= _tables()
    from apps.accounts.models import Role

    assert set(Role.objects.values_list("key", flat=True)) == {"super_admin", "admin", "engineer", "viewer"}
    executor = MigrationExecutor(connection)
    assert executor.migration_plan(executor.loader.graph.leaf_nodes()) == []


@pytest.mark.django_db
def test_no_missing_migrations():
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
