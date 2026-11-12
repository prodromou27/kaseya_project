# AGENTS.md — Engineering contract for Codex and other coding agents

## Product scope (non-negotiable)
Build **Odyssey Kaseya Analytics & Reporting Portal**, a **standalone** Django/React multi-customer internal analytics application for **Kaseya VSA X, IT Glue, and Autotask PSA**. It is unrelated to the Managed Services Hub or the existing custom asset-management platform. Vendor connectors are strictly **read-only for v1**.

**The current folder contains only documentation.** You must implement the actual application in this repository; never report that a feature is implemented because a design document describes it.

## Required order of work
1. Read `README.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/SECURITY.md`, `docs/API_INTEGRATIONS.md`, and `docs/TASKS.md`.
2. Inspect existing files and git status; preserve user changes.
3. Identify the next unchecked task ID in `TASKS.md`, record the implementation plan and dependencies.
4. Implement a **vertical slice** with backend schema/API, frontend UI, tests, and documentation together.
5. Run checks (format/lint/type-check/tests/build) and fix failures before completion.
6. Commit the completed slice if the environment permits, using a descriptive commit; do not claim a commit or CI run without evidence.
7. Update `TASKS.md`, `ROADMAP.md`, and `CHANGELOG.md` with actual results and remaining blockers.

## Mandatory engineering behavior
- **Never invent vendor endpoints, fields, pagination, or patch-applicability capabilities.** Verify official docs before implementing; use recorded fixtures only for offline contract tests.
- Do not silently substitute mock data for live data. Always label environment and fixture origin.
- Every customer-owned database model, ORM query, job payload, export and object-detail API must be customer-scoped and permission-checked on the server.
- Fail closed on unmapped source organizations and ambiguous mappings; never map by display name alone.
- Multi-customer analysis requires an explicit global role; customer membership alone must not grant cross-customer reporting.
- Do not fetch/store passwords, secrets, OTPs or sensitive document content from IT Glue; allowlist permitted endpoints and fields.
- Do not implement any POST/PATCH/PUT/DELETE against vendor APIs. Internal portal CRUD for catalogs, customers, roles and schedules is allowed with RBAC/audit.
- Do not disable TLS verification. Never log passwords, tokens, auth headers, or unredacted response bodies.
- Strict allowlist for connector base URLs, SSRF defenses and network egress policy.
- Report states must distinguish unavailable, unknown, stale, failed, excluded and not-applicable. Missing evidence is not compliance.
- All rate-limit handling must honor vendor `Retry-After` and cap retries/concurrency.
- Preserve last published good dataset until a new snapshot passes consistency checks.
- Do not add cloud AI telemetry, analytics SDKs or remote data transfer without formal authorization.

## Code standards
- Backend: Python 3.12+, Django 5.2 LTS, DRF, PostgreSQL, Celery/Redis; Ruff; pytest.
- Frontend: React 19, TypeScript `strict`, TanStack Query/Table, accessible responsive components, no direct vendor calls.
- Typed adapter interfaces and schema validation of external payloads.
- Explicit migrations, indexes, database constraints and test factories.
- Prefer small, cohesive modules and clear dependency inversion over generic frameworks.
- Reproducible Docker Compose dev/prod with non-root images, health checks and secrets injection.
- Include protected export files with retention and audit, CSV formula escaping, XLSX/PDF validation.

## Required tests per feature
- Positive case, missing fields, API failure, malformed data, pagination, rate limiting, stale data.
- Unauthorized access; cross-customer IDOR and leakage tests; background job scope and export scope tests.
- Snapshot rollback/atomic publication and idempotent replay tests.
- For software comparisons: version formats, product aliases, channels, unsupported/unknown/excluded results.
- For UI: empty/loading/error states and keyboard accessibility basics.

## Execution reporting format
For each completed slice report:
- Task IDs completed; files changed; assumptions; exact tests/commands with outcomes.
- Evidence from actual terminal output, including any failed checks.
- Vendor API features **verified from docs**, **fixture-tested**, **live-tested**, or **unavailable**.
- Next unblocked task; any security/deployment gates outstanding.

## Definition of done
Feature is done only when it has working code, migrations where needed, authorization checks, docs, tests, and a demonstrable end-user path. Production readiness additionally requires SSO, secret management, backup/restore, load/security testing, reviewed data handling and an approved pilot.

## Agent startup message
> Read AGENTS.md and the linked design files. Work through TASKS.md beginning at P0. Implement the actual app, not just scaffolding. Validate each phase and continue to the next task unless genuinely blocked by credentials or a decision that cannot be safely assumed. Do not use real customer credentials until approved. Always distinguish fixture tests from live API validation.
