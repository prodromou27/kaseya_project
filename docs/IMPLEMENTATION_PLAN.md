# Implementation plan — Codex / Claude Code execution playbook

**Deliverable of this file:** precise, actionable instructions to **build the application** from the documentation. The documentation package is **not itself an implemented application**.

## 0. Where to begin

**Create a dedicated private repository** named `odyssey-kaseya-portal`. This is not the Managed Services Hub, not the existing asset-management app, and not an MCP repository.

Keep these documents as your source-of-truth. The package already has `AGENTS.md`, `CLAUDE.md` and `README.md` at the root, and the other Markdown files under `docs/`. Copy the entire directory contents into the repository without rearranging files. The coding agent must compare actual repository state with these documents and must not invent previously implemented modules.

## 1. Build strategy

Use **vertical slices**, not a weeks-long scaffold. Each slice must contain: schema/migrations → service/adapter → API → UI → authorization → automated tests → docs → commit. Do not implement all backend endpoints without screens, nor all screens against fake responses without typed contracts.

### Phase gates

- **P0:** Identity foundation, customer isolation, audit, PostgreSQL, REST API, React shell, Compose, CI. Must pass unauthorized and cross-customer tests.
- **P1:** VSA read-only assets and software + catalog/version intelligence, fixture-backed demonstration, valid customer-scoped CSV.
- **P2:** Available/installed OS updates + reporting builder/exports + scheduled jobs + historical generations.
- **P3:** IT Glue config ingestion + reviewable device mappings.
- **P4:** Autotask companies/tickets + aggregate trends.
- **P5:** Production hardening: OIDC/MFA, approved credentials vault, TLS, monitoring, backups, isolated restore, load/pilot tests.

At each gate, create a **phase acceptance report** with actual command results, scope limitations and date, and update `TASKS.md`. Do not label fixture behavior as real tenant integration.

## 2. Project skeleton: exact target

```text
.
├── AGENTS.md, CLAUDE.md, README.md
├── docs/*.md
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── manage.py
│   ├── config/{settings,urls,celery}.py
│   ├── apps/{accounts,customers,integrations,inventory,software,patching,itglue,autotask,reporting,audit}/
│   └── tests/{unit,integration,api,fixtures}/
├── frontend/
│   ├── Dockerfile, package.json, tsconfig.json, vite.config.ts
│   ├── src/{app,features,components,lib}/
│   └── tests/
├── infra/{nginx,backup}/
├── compose.dev.yml, compose.prod.yml, .env.example
└── .github/workflows/{ci,security}.yml
```

The agent may refine folder names if documented and coherent; preserve a single authoritative source of truth for tenant logic and data contracts.

## 3. Detailed work sequence

### P0 — Build a secure vertical foundation

**P0.1 Repository and Docker.** Add backend/frontend scaffold, Dockerfiles, Compose PostgreSQL/Redis/reverse proxy/services, `.gitignore`, `.env.example`, health endpoints, CI, formatters and lock files. Demonstrate a fresh fixture-only boot.

**P0.2 Auth.** Implement one-time local bootstrap for dev and production onboarding; prepare OIDC implementation with mock IdP tests. For actual production, configure Microsoft Entra OIDC, MFA and session security before real data.

**P0.3 Tenants/RBAC.** Implement `Customer`, `CustomerMembership`, `IntegrationInstance`, `CustomerSourceMapping`. Enforce customer permission in ORM query policies and DRF views. Build customer selector and administrative customer view.

**P0.4 Audit/observability.** Append auth/customer/integration audit events, request IDs, structured logs, sanitized error responses; test secrets never appear in logs.

**P0 gate:** a user with Customer A cannot access Customer B via list/detail, search, guessed UUID, report, async job or artifact. Migrations run against real PostgreSQL. Backend tests, frontend type checks and production frontend build pass.

### P1 — VSA + software intelligence

**P1.1 Vendor adapter.** Implement VSA X Basic token auth via HTTPS; `GET /api/v3/assets` pagination `$top<=100` and `$skip`; normalize official `Data`, `Meta`, `InstalledSoftware` fields. Add bounded rate limit/backoff/Retry-After. Source org mapping must be reviewed.

**P1.2 Sync snapshots.** Add sync runs/checkpoints/staging/current generation, idempotent upsert and last-good publication. Test interrupted sync.

**P1.3 Asset UI.** Build asset list/detail, source badges, last seen, site/group, pagination/sort/filter, missing-field and stale states.

**P1.4 Software catalog.** Add products/aliases/channels/architecture, import workflow with preview and reviewer approval; immutable revisions. Implement comparator with reason codes and explicit unknown/unsupported/excluded categories.

**P1.5 Compliance UI/report.** Dashboard counts, product/version distribution, customer/site filters and CSV export with formula injection defense.

**P1 gate:** fixture-backed full sync, last-good retention, sample catalog comparison and tenant export pass. Do not claim actual third-party missing patch detection. Pilot source UI comparisons documented when credentials available.

### P2 — Windows update and reporting engine

**P2.1 OS update source.** Parse `Updates`, `AvailableUpdates`, `InstalledUpdates` from documented asset endpoints where returned; preserve missing sections as unavailable.

**P2.2 Reporting engine.** Add a report registry and typed filter schema; allowlist columns; provenance and snapshot pinning; CSV, XLSX and PDF artifacts with private storage, auth and expiry.

**P2.3 Scheduling/history.** Celery Beat + worker queues, timezones, schedule idempotency, job progress and audited downloads. Historical charts calculated from retained observations and documented denominators.

**P2 gate:** RPT-01–06 match underlying record sets, historical regeneration works, scheduled run and security tests pass.

### P3 — IT Glue

**P3.1 Connector.** Support region-specific base URL, `x-api-key`, JSON:API pagination, organizations/configurations with safe field allowlist. Never access `/passwords`.

**P3.2 Matching.** Build reviewed links to VSA assets; flag unmatched/ambiguous and differing serials/hostnames. No auto-merges.

**P3 gate:** fixtures and approved test scope match expected configuration counts; forbidden endpoint test passes.

### P4 — Autotask PSA

**P4.1 Connector.** API-only user + integration code; documented zone discovery and capped query paging. Minimize ticket fields; exclude cost/UDF/notes unless explicitly approved.

**P4.2 Analytics.** Ticket views, source links, statuses/priorities, date trends and evidence-backed device links.

**P4 gate:** sourced counts match approved test UI; company mapping leaks impossible; restricted API user behavior tested.

### P5 — Production validation

**P5.1 Security.** Real Entra OIDC + MFA, session policy, vault/rotation, egress allowlist, TLS, SELinux, reverse proxy headers and OWASP review.

**P5.2 Reliability.** Encrypted off-host backups and **isolated successful restore**, worker recovery, job queue health, retention, artifact storage and SIEM/audit forwarding.

**P5.3 Performance and operations.** Pilot load, database indexing, export stress, API budget characterization, monitoring, incident runbooks and security approval.

**P5 gate:** documented sign-offs and evidence in TESTING and SECURITY. Report code "feature-complete" only when features pass; reserve "production-ready" for full gate completion.

## 4. How to run with Codex CLI

These are example terminal steps; install the current supported Codex CLI from official distribution if needed. Do not hardcode passwords in CLI prompts.

```bash
mkdir odyssey-kaseya-portal
cd odyssey-kaseya-portal
git init
# Copy README.md, AGENTS.md, CLAUDE.md and docs/ from this package.
# Confirm tree and status:
git status --short
# Launch the coding agent in this directory:
codex
```

Paste the **coding-agent kickoff prompt** from section 6. Use a feature branch for each phase. Review each completion before merging. If the agent has no filesystem access, move to an agent-enabled IDE/terminal; chat text alone will not create or test code in your repository.

## 5. How to run with Claude Code

```bash
cd odyssey-kaseya-portal
claude
```

`CLAUDE.md` delegates to `AGENTS.md`; still paste the same kickoff prompt. Use appropriate permissions and review changes, especially migrations and secret-handling. Keep secrets in the host's secure secret store, **never** the prompt or chat history.

## 6. Copy/paste coding-agent kickoff prompt

> Build the complete Odyssey Kaseya Analytics & Reporting Portal in this repository. First read README.md, AGENTS.md, CLAUDE.md and all design files in docs/, especially IMPLEMENTATION_PLAN.md, TASKS.md, ARCHITECTURE.md, DATABASE.md, API_INTEGRATIONS.md, SECURITY.md, and TESTING.md. This is a standalone multi-customer internal reporting app unrelated to the Managed Services Hub or our separate asset-management app. Use Django 5.2 LTS/DRF, React 19/TypeScript, PostgreSQL, Celery/Redis and Docker Compose. Vendor connections are read-only. Inspect the repository and git status. Implement P0-01 onward as testable vertical slices with migrations, APIs, UI, authorization, fixtures, tests and docs. Execute checks and fix failures; continue systematically to subsequent phases. Verify actual vendor endpoints using official documentation; do not invent third-party patch applicability or use real credentials without approval. Update TASKS.md and CHANGELOG.md only with proven completed work. At each phase gate provide files changed, exact test results, known limitations, and next task. Start P0 now.

## 7. Continuation prompt for subsequent sessions

> Read AGENTS.md and TASKS.md. Inspect git status and recent commits. Summarize last proven phase gate and uncommitted changes. Continue from the next unchecked task, not from a rewrite. Preserve existing architecture and user changes. Run tests and explain evidence. Do not mark vendor integration live-tested unless approved real connectivity has been performed.

## 8. Independent review prompt (another coding agent)

> Act as an independent security/code reviewer for Odyssey Kaseya Analytics & Reporting Portal. Review the current phase implementation against AGENTS.md, SECURITY.md, DATABASE.md, API_INTEGRATIONS.md and TESTING.md. Focus on tenant isolation in ORM queries, background jobs and exports; vendor endpoint correctness and false patch-compliance claims; PII/secrets leakage; retry/snapshot atomicity; migrations; dependency and build health. Reproduce failures with tests and provide actionable findings ranked Critical/High/Medium/Low, including exact files and evidence. Do not make speculative claims. Do not rewrite the application without approval; fix confirmed critical correctness/security failures when authorized.

## 9. Implementation-phase completion report template

```markdown
# Phase Pn acceptance record
- Git revision / branch:
- Features implemented (task IDs):
- Database migrations applied:
- Backend tests: <command + test counts/result>
- Frontend tests/build: <command + result>
- Integration contract tests: <provider + fixtures + result>
- Live vendor verification: <not run / approved scope + evidence>
- Security / tenant tests:
- Known limitations and risks:
- Next phase tasks:
- Sign-off owner and date:
```

## 10. Do not do these things

- Do **not** claim a complete app because a login page or dummy dashboard renders.
- Do **not** silently skip auth, tenant isolation, migrations or report artifact permissions for speed.
- Do **not** pull source data directly from the browser.
- Do **not** use VSA's installed version as proof of a missing third-party patch.
- Do **not** create IT Glue password endpoints or VSA remote command/patch execution functions in v1.
- Do **not** auto-ingest sensitive Government customer data into an Odyssey-wide service without written approval.
- Do **not** give completion dates or production readiness guarantees without measured evidence.
