# Implementation task backlog (agent-ready)

**Status (2026-11-13):** P0-01 and P0-03 to P0-08 are done (`d799241`). P1-01 to P1-09 (`23550d1`) and P2-01 to P2-06 (`c483a8f`) are done and fixture-tested; there has been **no live VSA X validation**. P0-02 has not been booted, and the gates P0-09, P1-10 and P2-07 are open. Evidence: [PHASE_ACCEPTANCE_P0.md](PHASE_ACCEPTANCE_P0.md), [PHASE_ACCEPTANCE_P1.md](PHASE_ACCEPTANCE_P1.md), [PHASE_ACCEPTANCE_P2.md](PHASE_ACCEPTANCE_P2.md). Update only after tested code is merged/reviewed.

**Convention:** `P<phase>-<task>` task ID; C=critical, H=high, M=medium. Finish dependencies and acceptance conditions before marking checked.

> **VSA Phase 1 (2026-11-13):** Current release tracking moved to `PHASE1_TASKS.md` and `VSA_PHASE1_CROSSWALK.md`. This register is kept unchanged as history. P3 (IT Glue) and P4 (Autotask) are deferred.

## P0 — Application foundation

- [x] **P0-01 [C] Repository & quality setup:** Create Django/React monorepo, lock files, Ruff/ESLint/TypeScript strict, pytest/Vitest/Playwright, CI. **AC:** clean clone runs basic checks. — *Done `d799241`: clean clone ran lint, typecheck, 146 backend and 23 frontend tests, and the build. CI workflows written, not yet run (no remote).*
- [ ] **P0-02 [C] Docker developer stack:** PostgreSQL, Redis, backend, frontend, proxy, worker; persistent volumes, health checks. **AC:** demo stack boots; no externally exposed DB/Redis. — *Implemented (Dockerfiles, compose.dev/prod, nginx), **not booted**: no Docker in the dev environment.*
- [x] **P0-03 [C] Core database and migrations:** User, Customer, Membership, Role, IntegrationInstance, CustomerSourceMapping, AuditEvent. **AC:** migrate/up/down on PostgreSQL. — *Done `d799241`: migrations up/down tested on PostgreSQL 16.2.*
- [x] **P0-04 [C] Identity and sessions:** secure bootstrap admin + OIDC integration contract/mocks, server-side sessions. **AC:** admin login; anonymous denied; secure cookies/CSRF tests. — *Done `d799241`: OIDC tested against a mock IdP only; real Entra UAT is P5-01.*
- [x] **P0-05 [C] Tenant authorization:** Scope all DRF endpoints and services, deny default customer. **AC:** IDOR tests for list/detail/search/export/job. — *Done `d799241`: IDOR tests for list/search/detail/nested/report/artifact/job/revocation, plus a mutation check.*
- [x] **P0-06 [H] Customer admin UI:** customer CRUD, grant/revoke permissions, mappings review (internal write only). **AC:** role matrix and audit verified. — *Done `d799241`.*
- [x] **P0-07 [H] Audit and errors:** structured audit/logging, redaction, API error standard, request IDs. **AC:** events and sensitive-data redaction tests. — *Done `d799241`: includes a PostgreSQL append-only trigger.*
- [x] **P0-08 [H] UI foundation:** navigation, customer selector, account status, empty/error/loading states, accessible table shell. **AC:** React tests/build. — *Done `d799241`.*
- [ ] **P0-09 [C] Foundation gate:** PostgreSQL backend tests, frontend checks, security negatives, Demo seeding, proof of boot. **AC:** signed phase record. — *Open: needs a Docker boot, a green CI run and owner sign-off. Non-container boot and 5 Playwright E2E tests passed.*

## P1 — VSA X inventory and software versions

- [x] **P1-01 [C] Documented VSA adapter:** Basic token auth; `GET /api/v3/assets`; `$top/$skip` and response normalization. **AC:** doc/fixture contract tests. — *Done `23550d1`: verified against the api.vsax.net docs; 50 contract tests; fixture-only, not live-tested.*
- [x] **P1-02 [C] Safe sync engine:** rate budget, 429, Retry-After, checkpoint, idempotency, stage/promote. **AC:** interrupted sync retains last good dataset. — *Done `23550d1`: checkpointed, atomic publication; interrupted/replay/changing-source tests.*
- [x] **P1-03 [C] Organization mapping & quarantine:** source IDs to approved customers. **AC:** unmapped assets never leak into other customer. — *Done `23550d1`: per-org filtered collection, quarantine, DB customer-consistency triggers.*
- [x] **P1-04 [H] Assets UI:** device list/detail, site/group/OS/last seen, search/filter/pagination, freshness. **AC:** UI/API tests. — *Done `23550d1`.*
- [x] **P1-05 [C] Installed software:** normalize `Name/Publisher/Version`; preserve provenance and histories. **AC:** fixtures and counts reconcile. — *Done `23550d1`: counts reconcile across generation, API and CSV.*
- [x] **P1-06 [C] Software catalog:** product/alias/channels/architecture/reference revisions, import preview/review. **AC:** approved revision stored immutably. — *Done `23550d1`: separate-reviewer approval; revisions immutable (ORM and DB trigger).*
- [x] **P1-07 [C] Comparator:** current/outdated/newer/unknown/unsupported/excluded + reason codes. **AC:** edge-case comparison tests. — *Done `23550d1`: 32 edge-case tests.*
- [x] **P1-08 [H] Compliance UI:** product distribution, customer/site filters, drilldown and catalog evidence. **AC:** metric reconciliation. — *Done `23550d1`: metric reconciliation test.*
- [x] **P1-09 [C] Scoped CSV:** report provenance and spreadsheet formula injection defense. **AC:** negative security tests. — *Done `23550d1`: RPT-01/RPT-03 with pinned snapshot and provenance; injection tests.*
- [ ] **P1-10 [C] MVP gate:** demo data, fixture completeness, read-only vendor allowlist, optional approved live pilot. **AC:** phase record. — *Open: demo data, fixture completeness and read-only allowlist are done; needs the P0 gate, sign-off and an optional approved live pilot.*

## P2 — Windows updates, reports, history

- [x] **P2-01 [H] OS update collection:** VSA `Updates`, `AvailableUpdates`, `InstalledUpdates`, missing-data states. **AC:** correct OS classification and provenance. — *Done `c483a8f`: Updates/AvailableUpdates from the list endpoint; InstalledUpdates per device (budgeted, rotated, labelled carry-forward); fixture-only.*
- [x] **P2-02 [H] Patch views:** KB, severity where present, devices, scan freshness and unknown counts. **AC:** no false zeros. — *Done `c483a8f`: explicit not-collected/non-Windows states; no false zeros (tests + E2E).*
- [x] **P2-03 [C] Report schema/permissions:** templates, saved views, report runs, customer scope. **AC:** cross-tenant filters denied. — *Done `c483a8f`: templates, saved views, definitions; cross-tenant filters rejected.*
- [x] **P2-04 [H] XLSX/PDF:** professional layouts, data basis, streaming/private artifact storage. **AC:** valid files and matching row counts. — *Done `c483a8f`: string-typed XLSX, escaped PDF, identical row sets; private storage.*
- [x] **P2-05 [H] Scheduling:** Celery Beat, idempotent jobs, timezone and recipient controls. **AC:** duplicate suppression and revoke access tests. — *Done `c483a8f`: Beat dispatcher, DB-unique slots, re-authorisation, in-portal delivery only.*
- [x] **P2-06 [H] Historical snapshots:** pinned generations, catalog revision identity, trend charts. **AC:** old reports reproducible. — *Done `c483a8f`: pinned regeneration reproduces rows; trend endpoint and chart.*
- [ ] **P2-07 [C] Reporting gate:** all RPT-01–06 cases, negative export and retention tests. **AC:** phase record. — *Open: needs the P0/P1 gates, a live pilot and reporting-owner review (DEC-08/09).*

## P3 — IT Glue connector

- [ ] **P3-01 [H] Auth/region connector:** x-api-key JSON:API, US/EU/AU base URLs, paging and 429. **AC:** fixtures and auth failure tests.
- [ ] **P3-02 [C] Safe datasets:** organizations/configurations allowlist; passwords/secret endpoints prohibited. **AC:** forbidden routes fail closed.
- [ ] **P3-03 [H] Device/config matching:** reviewed serial/hostname/source identifiers and confidence. **AC:** ambiguous matches remain unlinked.
- [ ] **P3-04 [H] Reconciliation UI/report:** mismatched/missing devices, approved source links, exports. **AC:** tenant and quality tests.
- [ ] **P3-05 [C] IT Glue gate:** approved source count and restricted-data tests. **AC:** phase record.

## P4 — Autotask PSA connector

- [ ] **P4-01 [H] Restricted API user/zone:** headers, zoneInformation discovery, required permissions. **AC:** fixture and approved zone tests.
- [ ] **P4-02 [H] Company/ticket paging:** source company mapping, query caps/ID traversal, idempotent sync. **AC:** >500 records tested.
- [ ] **P4-03 [C] Sensitive-field minimization:** no costs/sensitive UDFs by default, redaction. **AC:** blocked fields tests.
- [ ] **P4-04 [H] Ticket UI/analytics:** status/priority/date, source links, verified device associations. **AC:** tenant leak negatives.
- [ ] **P4-05 [C] Autotask gate:** source counts and permission evidence. **AC:** phase record.

## P5 — Production-readiness and release

- [ ] **P5-01 [C] Entra SSO/MFA:** production identity policy, session hardening, bootstrap restrictions. **AC:** actual UAT identity test.
- [ ] **P5-02 [C] Secrets and connector egress:** vault/rotation, SSRF/TLS allowlist. **AC:** verified egress and redaction tests.
- [ ] **P5-03 [C] Encrypted off-host backup:** scheduled backups, keys and report artifacts. **AC:** recoverability and retention evidence.
- [ ] **P5-04 [C] Isolated restore test:** verify full functionality, roles, audit and pinned snapshots. **AC:** successful signed restore record.
- [ ] **P5-05 [H] Logs/monitoring:** sync failures, queue lag, source 429, stale data, mass export, audit forwarding. **AC:** alert simulation.
- [ ] **P5-06 [H] Performance/load:** representative 100k assets, millions of observations, large exports, rate budget. **AC:** measured/approved SLOs.
- [ ] **P5-07 [C] Security review:** OWASP/tenant leaks, dependency scan, secret scan, data-processing approval. **AC:** no unresolved critical findings.
- [ ] **P5-08 [C] Pilot customer:** VSA UI comparisons, report accuracy, IT Glue/PSA safe validation. **AC:** approved evidence.
- [ ] **P5-09 [C] Production gate:** administrator handbook, rollback, monitoring, backup restore and owner sign-off. **AC:** production go/no-go signed.

## Evidence register template

For each checked task add a short entry under a future `docs/PHASE_ACCEPTANCE_<phase>.md` with task ID, commit hash, exact commands, tests result, source-fixture/live status and reviewer.

## Codex remediation delivery - 2026-11-14

The historical P0-P5 checkboxes above remain acceptance history. Current VSA-only remediation work is tracked in CODEX_REMEDIATION_BACKLOG.md; evidence and files are in CODEX_VERIFICATION.md and CODEX_CHANGED_FILES.txt.

- [x] **CX-00** Independent implementation/UI baseline and prioritized audit.
- [x] **CX-01** Shared inventory/list/export filters, selected-device scope, URL state and column chooser.
- [x] **CX-02** Workflow navigation, scope/search, responsive shared controls and recovery boundary.
- [x] **CX-03** Current customer dashboard aggregates, exact drilldowns, source health and visible failures.
- [x] **CX-04** Persistent software/Windows filters, pagination, device links and honest export population.
- [x] **CX-05** Reconciliation progress and preview validation feedback; existing end-to-end comparison/workbook verified.
- [x] **CX-06** Grouped device investigation, persistent tabs/return filters, responsive layout and provenance.
- [x] **CX-07** Source-qualified hierarchy/group identity, ambiguous-ID refusal and pinned R10 network exports.
- [x] **CX-08** Bounded 100k normalized-inventory query benchmark and health-summary optimization; broader production load stays gated.
- [x] **CX-09** Internal immutable group-change proposals and independent review; vendor execution absent.
- [ ] **CX-10** Approved target environment, Docker/AlmaLinux health, real SSO/MFA, secrets/restore and representative live pilot.
- [ ] **CX-11** Independent security audit in the required isolated environment; local scans passed.

Final local evidence: **585 PostgreSQL tests**, **74 frontend tests**, **36-test full browser pass** including the network-export browser test, **34 desktop/mobile screens** with no overflow/JavaScript errors, clean lint/type/schema/build checks. No production deployment or new live vendor validation. First unchecked historical task remains **P0-02 / VSA0-02**, requiring Docker. Remaining UI refinements are explicitly recorded in the remediation backlog.
