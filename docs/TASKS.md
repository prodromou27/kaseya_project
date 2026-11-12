# Implementation task backlog (agent-ready)

**Status (2026-11-12):** P0-01 and P0-03 to P0-08 are implemented and tested at commit `d799241`. P0-02 is implemented but has not been booted (no Docker host). P0-09 is open. Evidence: [PHASE_ACCEPTANCE_P0.md](PHASE_ACCEPTANCE_P0.md). Update only after tested code is merged/reviewed.

**Convention:** `P<phase>-<task>` task ID; C=critical, H=high, M=medium. Finish dependencies and acceptance conditions before marking checked.

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

- [ ] **P1-01 [C] Documented VSA adapter:** Basic token auth; `GET /api/v3/assets`; `$top/$skip` and response normalization. **AC:** doc/fixture contract tests.
- [ ] **P1-02 [C] Safe sync engine:** rate budget, 429, Retry-After, checkpoint, idempotency, stage/promote. **AC:** interrupted sync retains last good dataset.
- [ ] **P1-03 [C] Organization mapping & quarantine:** source IDs to approved customers. **AC:** unmapped assets never leak into other customer.
- [ ] **P1-04 [H] Assets UI:** device list/detail, site/group/OS/last seen, search/filter/pagination, freshness. **AC:** UI/API tests.
- [ ] **P1-05 [C] Installed software:** normalize `Name/Publisher/Version`; preserve provenance and histories. **AC:** fixtures and counts reconcile.
- [ ] **P1-06 [C] Software catalog:** product/alias/channels/architecture/reference revisions, import preview/review. **AC:** approved revision stored immutably.
- [ ] **P1-07 [C] Comparator:** current/outdated/newer/unknown/unsupported/excluded + reason codes. **AC:** edge-case comparison tests.
- [ ] **P1-08 [H] Compliance UI:** product distribution, customer/site filters, drilldown and catalog evidence. **AC:** metric reconciliation.
- [ ] **P1-09 [C] Scoped CSV:** report provenance and spreadsheet formula injection defense. **AC:** negative security tests.
- [ ] **P1-10 [C] MVP gate:** demo data, fixture completeness, read-only vendor allowlist, optional approved live pilot. **AC:** phase record.

## P2 — Windows updates, reports, history

- [ ] **P2-01 [H] OS update collection:** VSA `Updates`, `AvailableUpdates`, `InstalledUpdates`, missing-data states. **AC:** correct OS classification and provenance.
- [ ] **P2-02 [H] Patch views:** KB, severity where present, devices, scan freshness and unknown counts. **AC:** no false zeros.
- [ ] **P2-03 [C] Report schema/permissions:** templates, saved views, report runs, customer scope. **AC:** cross-tenant filters denied.
- [ ] **P2-04 [H] XLSX/PDF:** professional layouts, data basis, streaming/private artifact storage. **AC:** valid files and matching row counts.
- [ ] **P2-05 [H] Scheduling:** Celery Beat, idempotent jobs, timezone and recipient controls. **AC:** duplicate suppression and revoke access tests.
- [ ] **P2-06 [H] Historical snapshots:** pinned generations, catalog revision identity, trend charts. **AC:** old reports reproducible.
- [ ] **P2-07 [C] Reporting gate:** all RPT-01–06 cases, negative export and retention tests. **AC:** phase record.

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
