# VSA-only implementation plan for Claude Code / Codex

**Do not implement IT Glue, Autotask PSA, Tenable or MCP in Phase 1.** The project is a standalone modular monolith. This document is instructions, not evidence of implementation.

## Architecture decisions

- Django REST Framework backend, React 19 + TypeScript frontend, PostgreSQL 16+, Celery worker/beat, Redis, Nginx/Caddy, Compose dev/prod on AlmaLinux. Pinned dependencies, typed contracts and real DB tests.
- Domain services independent of HTTP views so a future MCP adapter can reuse them (do not build it now).
- VSA read-only adapter with explicit endpoint allowlist and per-instance credentials. No direct vendor API calls from frontend; no unsupported DB/UI scraping.
- Customer membership/service RBAC on **every** query/job/report. Quarantine unreviewed VSA organizations.
- Collect snapshots asynchronously and promote only after successful completeness/quality checks. Keep last good generation; track source/observed/sync times.
- A separate disabled-by-default write gateway may eventually execute a single approved device move.

## Build order: vertical slices with passing gates

### VSA0 — Core platform

Repository quality, Django/React, Compose, PostgreSQL, TLS proxy, admin bootstrap + OIDC-ready auth, customer memberships, VSA instance scopes, audit, strict API permissions, migrations, CI with PostgreSQL. Developer demo must run without real VSA credentials. Gate: cross-customer IDOR and export authorization tests.

### VSA1 — Read-only inventory and hierarchy

VSA connection test (read token), endpoint capability matrix, org/site/group mapping, devices/assets pagination, normalized identities, complete snapshot lifecycle, device tables/details, agent status, NICs, disks, installed software. Gate: same hostname in two customers remains isolated; 429/timeout partial runs never corrupt last complete dataset.

### VSA2 — Excel onboarding + group network

Safe `.xlsx`/`.csv`, sheet mapping, high-confidence reconciliation to pinned VSA generation, manual review, missing/wrong group/site, progress and multi-sheet export. Hierarchy/group network device rollups, subnet derivation and duplicate IP review. Gate: deterministic 100-row fixture and duplicate-hostname tenant isolation tests.

### VSA3 — Software, OS patches, policy and initial reports

Reviewed reference catalog/import/version comparator, installed software classification, available/installed **OS** updates, patch policy detail/drift, explicit third-party patch status `UNVERIFIED` unless vendor capability proven. Report builder, CSV/XLSX/PDF with filters/provenance and controlled scheduling. Gate: software outdated does not imply pending third-party deployment; no-policy/unknown not fully compliant.

### VSA4 — Deep VSA analytics

Agent health, stale/offline thresholds, capacity/disk, reported security attributes, notifications, approved custom fields, inventory changes, lifecycle reference, exception reports, optional supported Advanced Reporting dataset research. Gate: timestamps/coverage and no fake audit actor attribution.

### VSA5 — Approved single-device group moves (optional)

Implement request/approval state machine, separate vaulted write credential and per-customer feature flag, exact immutable before/after, no self approval, single PUT/readback, unknown outcome protection. Keep OFF until independent production authorizations and pilot. Not a prerequisite for VSA read-only pilot.

### VSAP — Production hardening and acceptance

Entra OIDC/MFA, role/access review, TLS, secrets management, audit forwarding, backup + isolated restore, retention, performance/load, sync failures, monitoring, backup/restore evidence, authorized pilot with actual VSA version/API fields, operational runbooks and sign-off. Never mark production-ready without real sign-off.

## Implementation execution loop

For each unchecked `VSA*-XX` task in `PHASE1_TASKS.md`: inspect current repo and dependencies → short implementation plan → schema/service/connector/API/UI/tests → run format/lint/type/check/migrations/pytest/frontend builds/E2E as relevant → record exact evidence in `PHASE1_TASKS.md` and `CHANGELOG.md` → commit if permitted → next task. Do not stop at scaffolding, mocked UI, or reports without backend provenance.

When credentials or externally controlled approvals are missing: implement fixtures, contract tests, quality checks, and UI unavailable states, mark `LIVE_VALIDATION_PENDING`, and continue next unblocked tasks. Never fake a live success.

## Release criteria

A user can login, see only assigned customer VSA data, view devices and source freshness, compare Excel, view group networks and software/OS patch data, generate a filtered report, inspect sync failures, and reproduce a historical report. Group move requires its own independent go/no-go.
