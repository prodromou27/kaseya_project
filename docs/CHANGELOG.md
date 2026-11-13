# Changelog

All implementation claims require linked evidence. Use semantic versions for application releases once a working application exists.

## [Docs 0.1.0] — 2026-11-12

### Added
- Full project README and scope restrictions.
- Architecture and multi-customer database model.
- Verified public-documentation-based vendor API capability register and limitations.
- Security, AlmaLinux/Docker deployment, admin and engineer workflows.
- Reporting metric definitions, QA test matrix and production readiness gates.
- Implementation roadmap, task checklist, Codex/Claude agent instructions and decision log.

### Not implemented
- No source code for the Django/React application in this package.
- No deployed portal, working vendor connector, live customer data, tests, or production sign-off.

## [0.4.0-dev] — 2026-11-13 (unreleased; VSA Phase 1, commits `ea26682`, `dcecf60`)

Evidence: [IMPLEMENTATION_EVIDENCE.md](IMPLEMENTATION_EVIDENCE.md). **Fixture-tested only; no live VSA validation.**

### Added
- VSA1: org > site > group explorer from `/sites`, `/groups` and `/devices`. Devices also gain NIC/IP/MAC, disk and security observations, a group network view (derived CIDRs, duplicate-IP/MAC-reuse review flags) and MAC/IP search. The UI states explicitly that third-party patch status is *unavailable*.
- VSA2: an **Onboarding check**. Upload an expected device list (.xlsx/.csv) and match it deterministically against the customer's latest complete VSA snapshot. Results come out in eight classifications plus secondary flags and an unexpected-device set. Uncertain matches get a review queue, and the run exports as a 10-tab XLSX or as CSV. Runs are immutable and pinned to a generation.
- `defusedxml` dependency (hardens workbook XML parsing).
- VSA3-04: **Patch policies**, covering budgeted per-device applied policies, policy definitions (configuration only) and an explicit No Policy state that is kept distinct from unknown. Also a two-person-approved expected-policy baseline with drift, a device Policies tab and report R08. The onboarding `NO_PATCH_POLICY` flag is now evaluated (commit `ff7a956`).
- VSA4: **Device health** covers connectivity, agent installed, agent version (against an approved minimum), system disk free space, antivirus and firewall. Each is a complete partition with explicit unknown buckets, under two-person-approved thresholds. The documented CPU, memory and aggregate security fields are kept verbatim. Adds reports R09, R13 and R14; the onboarding `OLD_AGENT` flag is now evaluated (commit `b345b8f`).
- VSA1-01: an administrator **connection test** (`GET /api/v3/ratelimits`) reports an explicit outcome, latency and the reported per-endpoint rate limits. VSA2-05: **expected subnets** per site/group, two-person approved, flag addresses outside them, and addresses that changed since the previous snapshot are flagged too. Both are review observations only (commit `5dbb567`).
- VSA4-04: **Inventory changes** shows the differences between two complete snapshots and adds report R16. No change time or person is invented. A device **Onboarding** tab lists the onboarding checks that involved the device (commit `136ddb6`).
- AlmaLinux deployment: an as-implemented runbook, `.env.prod.example`, a host preflight script and a secrets preparation script (owners, modes, SELinux labels), and SELinux-aware Compose binds. Docker-published ports bypass firewalld, so the runbook adds `PORTAL_BIND_ADDRESS` and DOCKER-USER guidance. Not yet executed on a host.

### Not changed
- VSA X stays read-only. Device moves remain disabled (VSA5 BLOCKED_APPROVAL).

## [0.3.0-dev] — 2026-11-13 (unreleased; P2 Windows updates, reports, history, commit `c483a8f`)

Evidence: [PHASE_ACCEPTANCE_P2.md](PHASE_ACCEPTANCE_P2.md). **Fixture-tested only.**

### Added
- VSA X OS update sections: available updates (list endpoint) and installed updates (per-device, budgeted), with an explicit status for each device.
- Windows updates view, an OS-update tab on each asset, and the RPT-04 report.
- XLSX and PDF output for every report, plus RPT-05 (version distribution) and RPT-06 (stale devices).
- Report templates endpoint, saved views and report definitions.
- Timezone-aware schedules with in-portal delivery, scheduled read-only syncs and an expired-artifact purge.
- Regeneration of a report from its original pinned snapshot, a history/trend endpoint and a dashboard chart.

### Security
- XLSX cells are string-typed (no formulas). PDF text is escaped. Filters cannot reference another customer's records. Schedule recipients are re-authorised on every run.

## [0.2.0-dev] — 2026-11-12 (unreleased; P1 VSA X + software versions, commit `23550d1`)

Evidence: [PHASE_ACCEPTANCE_P1.md](PHASE_ACCEPTANCE_P1.md). **Fixture-tested only. No live VSA X validation.**

### Added
- A read-only VSA X adapter based on the documentation at https://api.vsax.net/ (assets, organizations), with a capability record.
- A sync engine with checkpoints, quarantine, consistency checks and atomic publication of generations.
- Inventory and installed-software views with freshness and fixture labelling.
- A reviewed software catalog: import preview, separate-reviewer approval and immutable revisions.
- A version comparator (current / outdated / newer / unknown / unsupported / excluded, each with a reason code) and approved exceptions.
- Software version compliance view and RPT-01/RPT-03 CSV exports with a provenance block.
- Admin tools: organisation discovery, sync quarantine and the catalog workflow.

### Not claimed
- Third-party patch applicability or vulnerability state. Classification is version comparison only.

## [0.1.0-dev] — 2026-11-12 (unreleased; P0 foundation, commit `d799241`)

Evidence: [PHASE_ACCEPTANCE_P0.md](PHASE_ACCEPTANCE_P0.md).

### Added
- Django 5.2 LTS / DRF API on PostgreSQL 16 with customers, memberships, seeded roles and capabilities, integration instances and reviewed source mappings.
- Central customer-scope policy. Cross-customer access returns an audited 404.
- Local bootstrap admin, OIDC relying party (tested against a mock IdP), secure server-side sessions, CSRF protection and login throttling.
- Append-only audit trail (including a DB trigger), redacted JSON logging, request IDs and a standard error envelope.
- Customer-scoped async report jobs with private artifacts, CSV formula-injection defence and re-authorised downloads. The first report type is the audit-log CSV.
- React 19 / TypeScript SPA: login, customer selector, dashboard, customer administration, system administration, reports.
- Dockerfiles, Compose dev/prod files, nginx proxy, CI and security workflows.

### Security
- Upgraded djangorestframework 3.16.1 → 3.18.3 after pip-audit reported CVE-2026-114136/7/8.

### Not yet verified
- Docker Compose boot, CI execution, Entra ID SSO, and every vendor connector (none implemented yet).

## [App release] — Not yet released

Coding agent must add actual commits, passing test evidence, migrations, deployment/validation results and limitations before publishing an application version.
