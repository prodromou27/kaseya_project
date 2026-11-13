"""VSAP-02: verify a restored database before it is trusted (restore drill). Read-only.

Checks: no unapplied migrations; integrity triggers present (they are not re-created by data-only tools, so a
partial restore is caught); no cross-customer rows; at least one active super administrator; current generations
are published. Prints a JSON report; exit code 1 when any check fails.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

REQUIRED_TRIGGERS = {
    "audit_auditevent_no_update_delete",
    "inventory_observation_customer_check",
    "onboarding_result_customer_check",
    "onboarding_run_customer_check",
    "patching_applied_policy_customer_check",
    "patching_device_update_customer_check",
    "patching_observation_customer_check",
    "patching_policy_obs_customer_check",
    "patching_policydef_customer_check",
    "software_installation_customer_check",
    "software_result_customer_check",
    "software_revision_immutable",
    *(
        f"{t}_customer_check"
        for t in (
            "inventory_networkadapterobservation",
            "inventory_ipaddressobservation",
            "inventory_diskobservation",
            "inventory_securityobservation",
            "inventory_organizationnode",
            "inventory_sitenode",
            "inventory_groupnode",
        )
    ),
}

# (label, SQL returning one integer that must be 0)
CONSISTENCY_SQL = [
    (
        "observation_customer_mismatch",
        "SELECT count(*) FROM inventory_assetobservation o "
        "JOIN integrations_datasetgeneration g ON g.id = o.generation_id WHERE g.customer_id <> o.customer_id",
    ),
    (
        "asset_customer_mismatch",
        "SELECT count(*) FROM inventory_assetobservation o JOIN inventory_asset a ON a.id = o.asset_id "
        "WHERE a.customer_id <> o.customer_id",
    ),
    (
        "current_generation_not_published",
        "SELECT count(*) FROM integrations_datasetgeneration WHERE is_current AND state <> 'published'",
    ),
    (
        "reconciliation_result_customer_mismatch",
        "SELECT count(*) FROM onboarding_reconciliationresult r JOIN onboarding_reconciliationrun n ON n.id = r.run_id "
        "WHERE n.customer_id <> r.customer_id",
    ),
]

COUNTS = {
    "customers": "SELECT count(*) FROM customers_customer",
    "users": "SELECT count(*) FROM accounts_user",
    "active_super_admins": "SELECT count(*) FROM accounts_user u JOIN accounts_role r ON r.id = u.global_role_id "
    "WHERE u.is_active AND r.key = 'super_admin'",
    "integration_instances": "SELECT count(*) FROM integrations_integrationinstance",
    "approved_mappings": "SELECT count(*) FROM customers_customersourcemapping WHERE mapping_status = 'approved'",
    "current_generations": "SELECT count(*) FROM integrations_datasetgeneration WHERE is_current",
    "assets": "SELECT count(*) FROM inventory_asset",
    "audit_events": "SELECT count(*) FROM audit_auditevent",
    "reconciliation_runs": "SELECT count(*) FROM onboarding_reconciliationrun",
}


class Command(BaseCommand):
    help = "Verify a restored database (VSAP-02 restore drill). Read-only; JSON report; exit 1 on failure."

    def handle(self, *args: Any, **options: Any) -> None:
        report: dict[str, Any] = {"checks": {}, "counts": {}}
        executor = MigrationExecutor(connection)
        unapplied = executor.migration_plan(executor.loader.graph.leaf_nodes())
        report["checks"]["unapplied_migrations"] = {
            "ok": not unapplied,
            "value": [f"{m.app_label}.{m.name}" for m, _ in unapplied],
        }

        with connection.cursor() as cur:
            cur.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
            present = {r[0] for r in cur.fetchall()}
            missing = sorted(REQUIRED_TRIGGERS - present)
            report["checks"]["integrity_triggers"] = {"ok": not missing, "missing": missing}
            for label, sql in CONSISTENCY_SQL:
                cur.execute(sql)
                n = cur.fetchone()[0]
                report["checks"][label] = {"ok": n == 0, "value": n}
            for label, sql in COUNTS.items():
                cur.execute(sql)
                report["counts"][label] = cur.fetchone()[0]
            cur.execute("SELECT max(created_at) FROM audit_auditevent")
            latest = cur.fetchone()[0]
            report["latest_audit_event"] = latest.isoformat() if latest else None

        report["checks"]["active_super_admin"] = {"ok": report["counts"]["active_super_admins"] > 0}
        report["ok"] = all(c["ok"] for c in report["checks"].values())
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if not report["ok"]:
            raise CommandError("Restore check failed.")
