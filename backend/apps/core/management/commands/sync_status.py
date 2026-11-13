"""Read-only sync diagnosis for operators: `docker compose ... exec backend python manage.py sync_status`.

Prints integrations, mappings, schedules, recent sync runs and whether the Celery worker answers. Never prints
credentials, tokens or vendor payloads. Ends with plain-language findings.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

HINTS = {
    "integration_disabled": "The integration is disabled: Admin -> Integrations -> Enable.",
    "mapping_not_approved": "The mapping is not approved: Admin -> Mapping review.",
    "credential_unavailable": "No usable API credentials: Admin -> Integrations -> Set credentials.",
    "auth_failed": "VSA X rejected the credentials (401/403): check the token and its permissions.",
    "egress_blocked": "The VSA host is not allowed or resolves to a private address: Admin -> Integrations -> "
    "Allowed API hosts (private addresses need CONNECTOR_APPROVED_PRIVATE_CIDRS).",
    "rate_limited": "VSA X rate limit reached; the run resumes later.",
    "vendor_unavailable": "VSA X did not answer or returned a server error; check network/DNS/firewall from the host.",
    "row_count_drop_guard": "The device count dropped sharply, so the snapshot was not published (protects good data).",
    "retry_budget_exhausted": "VSA X kept failing or rate limiting; the run gave up after its retries.",
    "malformed_page": "VSA X returned data in an unexpected shape; see the backend/worker logs.",
    "bad_response": "VSA X returned an unexpected response; see the worker logs.",
    "endpoint_not_allowed": "A request path is not on the read-only allowlist (report this; it is a bug).",
    "internal_error": "Unexpected error in the worker; see `docker compose logs worker`.",
}


class Command(BaseCommand):
    help = "Show integration, mapping, schedule and sync-run status, and what is blocking syncs."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--runs", type=int, default=10, help="How many recent sync runs to show.")
        parser.add_argument("--no-worker-check", action="store_true", help="Skip the Celery worker ping.")

    def handle(self, *args: Any, **options: Any) -> None:
        from apps.customers.models import CustomerSourceMapping
        from apps.integrations.models import IntegrationInstance, SyncRun, SyncSchedule
        from apps.integrations.secrets import credential_source

        out, findings = self.stdout.write, []
        now = timezone.now()

        out("== Integrations")
        integrations = list(IntegrationInstance.objects.order_by("name"))
        if not integrations:
            findings.append("No integration exists: Admin -> Integrations -> Add an integration.")
        for i in integrations:
            cred = "n/a (fixture)" if i.is_fixture else credential_source(i)
            out(
                f"  {i.name}: provider={i.provider} enabled={i.enabled} fixture={i.is_fixture} base_url={i.base_url} "
                f"credentials={cred} last_test={i.last_test_outcome or 'never'}"
            )
            if not i.enabled:
                findings.append(f"Integration '{i.name}' is disabled.")
            if not i.is_fixture and cred == "none":
                findings.append(f"Integration '{i.name}' has no credentials.")
            if not i.is_fixture and i.last_test_outcome and i.last_test_outcome != "ok":
                findings.append(
                    f"Last connection test of '{i.name}' failed: {HINTS.get(i.last_test_outcome, i.last_test_outcome)}"
                )

        out("== Mappings (VSA organisation -> customer)")
        mappings = list(
            CustomerSourceMapping.objects.select_related("customer", "integration_instance").order_by("customer__code")
        )
        if not mappings:
            findings.append("No organisation is mapped to a customer: Admin -> Integrations -> Discover orgs.")
        for m in mappings:
            via = m.integration_instance.name
            out(f"  {m.customer.code}: org {m.external_org_id} via {via} status={m.mapping_status}")
        if mappings and not any(m.mapping_status == "approved" for m in mappings):
            findings.append("No mapping is approved: Admin -> Mapping review -> Approve.")

        out("== Sync schedules")
        schedules = list(SyncSchedule.objects.select_related("mapping__customer").order_by("next_run_at"))
        for s in schedules:
            due = "due now" if s.next_run_at <= now else f"next {s.next_run_at:%Y-%m-%d %H:%M} UTC"
            last = s.last_run_at or "never"
            out(f"  {s.mapping.customer.code}: every {s.interval_hours} h, enabled={s.enabled}, {due}, last {last}")
        approved_without = [m for m in mappings if m.mapping_status == "approved" and not hasattr(m, "schedule")]
        for m in approved_without:
            findings.append(f"Approved mapping for {m.customer.code} has no schedule (Admin -> Sync schedules).")

        out(f"== Last {options['runs']} sync runs")
        runs = list(SyncRun.objects.select_related("customer").order_by("-created_at")[: options["runs"]])
        if not runs:
            findings.append("No sync has ever been requested (no schedule ran and nobody pressed Sync now).")
        for r in runs:
            out(
                f"  {r.created_at:%Y-%m-%d %H:%M} {r.customer.code} {r.trigger} state={r.state} "
                f"error={r.error_code or '-'} fetched={r.fetched_count} accepted={r.accepted_count} "
                f"quarantined={r.quarantined_count} api_requests={r.api_requests}"
            )
        if runs:
            latest = runs[0]
            if latest.state in ("failed", "partial") and latest.error_code:
                findings.append(f"Latest run {latest.state}: {HINTS.get(latest.error_code, latest.error_code)}")
            stuck = [r for r in runs if r.state in ("queued", "running") and (now - r.created_at).total_seconds() > 900]
            if stuck:
                findings.append(
                    f"{len(stuck)} run(s) queued/running for over 15 minutes: the worker may be down "
                    "(docker compose ps; logs worker)."
                )

        if not options["no_worker_check"]:
            out("== Worker")
            try:
                from config.celery import app

                replies = app.control.ping(timeout=3.0) or []
            except Exception as exc:  # broker unreachable etc.; message only
                replies = []
                out(f"  ping failed: {type(exc).__name__}")
            out(f"  workers answering: {len(replies)}")
            if not replies:
                findings.append("No Celery worker answered: syncs and reports cannot run (check the worker container).")

        out("== Findings")
        for f in findings or ["Nothing obviously blocking. If data is still missing, check the latest run above."]:
            out(f"  - {f}")
