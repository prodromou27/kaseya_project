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

- [x] **P5-01 [C] Entra SSO/MFA:** ~~production identity policy~~ — *Not required (product owner, 2026-11-15, DEC-03). Local accounts with password policy, throttling, session timeout and audit are the production sign-in.*
- [ ] **P5-02 [C] Secrets and connector egress:** vault/rotation, SSRF/TLS allowlist. **AC:** verified egress and redaction tests.
- [ ] **P5-03 [C] Encrypted off-host backup:** scheduled backups, keys and report artifacts. **AC:** recoverability and retention evidence.
- [ ] **P5-04 [C] Isolated restore test:** verify full functionality, roles, audit and pinned snapshots. **AC:** successful signed restore record.
- [ ] **P5-05 [H] Logs/monitoring:** sync failures, queue lag, source 429, stale data, mass export, audit forwarding. **AC:** alert simulation. — *PARTIAL (2026-11-15): in-portal System status (Settings → System status, `GET /api/v1/system/status/`, super admin) reports worker/broker, queue lag and stuck runs, 24 h sync failures by cause incl. 429, stale sources, export volume per user and failed sign-ins; dashboard banner on errors. Tested by simulated conditions. **Pending:** external alert delivery and audit-log forwarding (needs the operator's monitoring target).*
- [ ] **P5-06 [H] Performance/load:** representative 100k assets, millions of observations, large exports, rate budget. **AC:** measured/approved SLOs. — *PARTIAL (2026-11-16): `benchmark_inventory --related` measures 100k devices with 2.3 M related observation rows (software, OS updates, patch status/policy, servers) and large report exports; servers list 49.6→1.9 s, patch-policy summary 39.5→4.0 s, scorecard 141→10.5 s, servers all-devices 74→6 s, 100k-row CSV/XLSX exports 12/36 s. Proposed SLOs in `CODEX_PERFORMANCE.md`. **Pending:** owner approval of SLOs, concurrency and target-host measurement, live sync throughput.*
- [ ] **P5-07 [C] Security review:** OWASP/tenant leaks, dependency scan, secret scan, data-processing approval. **AC:** no unresolved critical findings. — *PARTIAL (2026-11-16): focused local review of all features since the first review, recorded in `CODEX_SECURITY_REVIEW.md`: 2 findings fixed (credential references could name server secrets - low; semgrep blocker), no critical/high; pip-audit, bandit, npm audit, semgrep clean; history pattern scan clean. **Pending:** gitleaks run in CI, independent sandboxed audit (CX-11) and data-processing approval.*
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


## Onboarding agent groups - CIDR-01

- [x] **CIDR-01** Treat onboarding groups as legitimate temporary installation destinations; allow administrators to mark group purpose and propose source-qualified group subnets; show evidence-based destination suggestions without executing a move.

Plan/dependencies: reuse current approved mapping/snapshot queries, ExpectedSubnet review lifecycle, group network screen and existing device Operations proposal UI. Add persistent source-qualified purpose settings and nullable source identity for legacy subnet rules; qualify new rules; test role/customer/source isolation, ambiguous overlaps and absent evidence; regenerate schema and run affected backend/frontend/browser checks. P0-02/VSA0-02 remains externally blocked by Docker. No new vendor endpoints or credentials are required.

Result: implemented and fixture-verified. Full PostgreSQL suite 589 passed; full frontend suite 78 passed; dedicated administrator-to-independent-reviewer browser workflow passed. Vendor writes remain absent. See ONBOARDING_GROUPS.md for controls, exact checks and evidence.


## LIST-01 - simplify device lists and group navigation

- [x] **LIST-01** User-prioritized device/group usability and persistent named list layouts.

Plan: extend existing customer/owner-scoped SavedView with validated presentation (columns, density, page size); retain filter-only compatibility. Simplify device toolbar, debounce server search, expose active removable filters, source-qualified site/group options and sortable table headers. Improve shared table paging/empty/update feedback and controlled layouts. Add searchable group list with scoped device links and onboarding purpose, retaining hierarchy. Dependencies: existing scoped inventory/facets/hierarchy, SavedView API/RBAC, bounded pagination and read-only fixtures. Validate backend ownership/IDOR/layout input and UI keyboard/layout/search/paging/navigation with desktop/mobile browser evidence. First unchecked historical gate remains P0-02/VSA0-02 (Docker unavailable).

LIST-01 result: source commit fae7e6f; 603 PostgreSQL tests, 85 frontend tests, 40/40 full browser scenarios, migration rollback/forward compatibility, schema/types/lint/build passed. Before/after and actual failures corrected: LIST_USABILITY.md. Fixture-only; production/live gates remain open.

## LIST-02 - software and Windows-update investigation

- [x] **LIST-02** Separate overview/investigation/admin workflows, complete update-coverage paging, and keep searched exports accurate.

Plan/dependencies: reuse LIST-01 tables, URL state and debounce; split software overview/installations/exceptions and Windows records/collection coverage/common updates into accessible tabs. Add software/device/version and update-title/device searches through shared scoped query helpers used by live lists and pinned exports. Fix the 200-device coverage truncation, add a separately labelled coverage report, preserve unknown/failed/unsupported evidence and read-only vendor access. No new vendor field or schema migration is needed. Validate list/report parity, >200-row coverage, cross-customer denial, pinned replay, UI keyboard/loading/errors/paging and browser workflows. Stop when this bounded slice passes checks; further saved layouts and reconciliation remain separately tracked. Historical P0-02 Docker acceptance stays open.

Result: implementation 7a6df23; full backend suite 614 passed; final feature rerun 11 passed after restoring coverage device type; 89 frontend tests and all 43 browser scenarios passed. Ruff/types/lint/build/schema/migration-drift checks passed. Evidence, corrected failures and rollout limits: INTELLIGENCE_LISTS.md. Fixture-only; no deployment/live claim. Next product slice: LIST-03 guided Excel reconciliation.


## CIDR-02 - visible onboarding placement suggestions

- [x] **CIDR-02** Show per-device destination hints on the onboarding group itself; prioritize network evidence and use naming only as weaker evidence.

Plan/dependencies: reuse current approved source snapshots, existing group settings/subnet review and manual move proposal. Add a paginated customer/source/group-scoped read endpoint and group UI. Rank approved destination CIDRs, then valid subnets observed on existing destination peers, then explicit group/peer hostname naming tokens. Explain each basis and ambiguity; exclude current/inactive/onboarding/foreign destinations; reject stale or revoked evidence. No schema or vendor API change. Validate ranking, missing/malformed evidence, boundaries, paging, query count and UI/manual workflow. Historical Docker/live/production gates remain open.

Result: implementation 32a8407; 624 full backend tests, final 22-case backend rerun, 94 frontend tests and 43/43 full browser scenarios passed. Final desktop/phone captures have no JavaScript errors or page overflow. Identically named destinations now show site/stable group ID. No migration required. Actual commands, corrected failures and screenshots: ONBOARDING_SUGGESTIONS.md. Fixture-only; production/live gates remain open. Next product work remains LIST-03.


## Customer reporting and management (beyond VSA X) - 2026-11-15

Scope (operator direction): the portal exists to report on and manage each customer better than VSA X alone. All
modules below are read-only toward VSA X, customer-scoped, audited where they change portal-owned data, and
fixture-verified only (no live VSA X validation).

- [x] **OPS-01** `vsa_probe` read-only command: which VSA X sections return data (field names/counts only). Commit d8a955e.
- [x] **OPS-02** System status page/API for super admins (worker, queue lag, sync failures, stale data, exports, failed sign-ins); dashboard banner. Commit aa47613. *Open: external alert delivery and audit forwarding (needs a target).*
- [x] **CMP-01** Compliance baselines (11 rule kinds, pass/fail/unknown with reasons, score, rule and group breakdowns, admin editor). Commit 459e7a9.
- [x] **TPP-01** Third-party patch exposure: catalog version state x patch-policy rule coverage; never shown as deployed. Commit 11dd83d.
- [x] **NET-03** Subnet inventory with approved-subnet match, outside-scope review signal and one-click proposals (feeds CIDR-02 suggestions). Commit c0a4d27.
- [x] **RPT-07** Custom report builder (7 sources, columns, typed filters, preview, generate, save, schedule). Commit bde71fb.
- [x] **CRM-01** Customer workspace: Summary tab per customer (health, compliance, patching gaps, subnets, sources, recent reports), each number linked to its investigation.
- [x] **CRM-02** Monthly customer scorecard (all areas, 30-day comparison from retained snapshots), PDF from the customer Summary, schedulable. Commit b93c48b.
- [x] **CRM-03** Live-evaluated report figures (compliance, third-party, subnets, scorecard) are kept with the run; regeneration reproduces them. Commit 3125ec2.
- [x] **UX-07** Catalog quick-add from Installed programs; stale onboarding suggestions explained with Sync now (operator feedback). Commit e8e0385.
- [x] **CIDR-03** Destination plan (devices grouped by target group/site, ties and no-evidence lists, CSV move list) and leading-letter naming evidence. Operator feedback 2026-11-15.
- [x] **OPS-03** Cleanup centre (duplicates, stale/never seen, no group, onboarding leftovers, no agent, missing serial; CSV to-do list). Commit bbb95a2.
- [x] **OPS-04** Alerts & watchlists: per-user watches (new device, offline > N days, disk critical, program appears, compliance below), in-portal bell and Alerts page. *Open: email digest (DEC-09).* Commit 44cc735.
- [x] **CRM-05** All-customers overview: customers side by side (health, updates, software, compliance, freshness), sorting, CSV, drill-down. Commit 5f79092.
- [x] **AUT-01** Automation health: workflow results per customer device, task/workflow catalog, workflow-failure alerts. *Limitation: scheduled task runs are not listable read-only.*
- [x] **SCR-01** Script collectors: allowlisted script output variables per device, device tab, compliance rule, report source.
- [x] **CF-02** Organisation/site/group custom fields (allowlisted names only) on the customer page (organisation, each site and group) and in custom reports.
- [x] **GR-01** Patch global rules (count toward third-party coverage) and scopes (criteria, device count, used by).
- [x] **VSA5-EXEC** Approved group moves executed in VSA X (gated: feature flag off, separate write token, approval, read-back).
- [x] **SRV-01** Servers & owners (portal-only): servers detected from the OS name or marked by hand, owner groups with contact, per-server patching/upgrade needs, report per owner, email-owner summary.
- [x] **CFA-01** Audit of existing custom field reads, write pattern, inventory, RBAC and imports; API findings in `CUSTOM_FIELD_ASSIGNMENT_IMPLEMENTATION.md` (route inconsistency confirmed).
- [x] **CFA-02** Field discovery (`GET /customFields`), eligibility (device context, not read-only, not expired, not credential-like, portal-editable), Field overview.
- [x] **CFA-03** Device selection: filters, selection across pages, "all matching" resolved to a fixed list, workstations only.
- [x] **CFA-04** Paste and TXT/CSV/XLSX import with column mapping (optional value per device); exact matching engine (device ID → serial → FQDN → hostname) with ambiguity resolution.
- [x] **CFA-05** Live preview (device-level vs inherited via `/usage`), typed value validation, actions and summary, overwrite acknowledgement.
- [x] **CFA-06** Gated writer (ADR-031): documented assign/update only, three switches + validated route + separate token; `vsa_custom_field_validate`.
- [x] **UX-05** Shorter menu: daily work and VSA X changes always visible, other groups folded (current page's group opens itself; Find a page searches all; every URL unchanged) (product owner, 2026-11-22).
- [x] **UX-04** Find a device from the header across all permitted customers (type-ahead, opens the device); dashboard shows every customer's health with none selected and the full customer summary with one selected (product owner, 2026-11-20).
- [x] **UX-03** Fewer steps for reports: download offered where the report was requested; save and schedule from the report form in one step (product owner, 2026-11-20).
- [x] **UX-02** Fewer steps for group moves: propose a whole destination at once, approve and move in one step, decide several proposals together (product owner, 2026-11-20).
- [x] **UX-01** Fewer steps for custom field changes: preview starts by itself, one confirmation, stale previews refresh on open, administrators get a *Waiting for you to apply* list (product owner, 2026-11-19).
- [x] **CFA-11** One token is enough: writes use the integration's API token unless an optional separate write token is set (product owner, 2026-11-18).
- [x] **CFA-10** Setup in the portal, admins apply: separate write token entered encrypted in Settings → Integrations (purpose-bound, write-only, audited, cleared on base URL change); test-workstation route validation in the portal; server variable becomes an emergency stop (default on); engineers prepare/preview, only administrators apply or retry.
- [x] **CFA-07** Celery execution: one device at a time, re-check before write, sent-once, 429 backoff, read-back with bounded retries, resume-safe, cancellation, duplicate protection, approval threshold.
- [x] **CFA-08** Audit per request/decision/device, history, CSV/XLSX report (six sheets, formula-neutralised), retry of failed devices, device page tab.
- [x] **CFA-09** Tests: 17 backend, 4 frontend, 1 browser scenario + accessibility. **Pending:** live validation on an authorised test workstation (route, Boolean/Date formats, inheritance) - not claimed.
- [x] **CAT-01** Reference versions from the VSA 10 Application Catalog: pasted table matched to installed programs, reviewed through the existing catalog import (no API endpoint exists; nothing fetched).
- [x] **CAT-02** Automatic daily update from the VSA application catalog page: version increases for approved products apply automatically (ADR-030); new products/decreases/warnings wait for approval; status and Check now in Settings.
- [x] **CAT-03** Catalog matching keeps version-series lines and bracketed editions apart (127 of 303 live entries were being skipped); coverage of the last check shown in Settings.
- [x] **SRV-02** Server owner follow-ups: monthly report schedule per owner, owner pick-list on Reports, Servers card on the customer summary, Servers section on the monthly scorecard.
- [ ] **CRM-04** Live validation of the new modules on the operator's tenant after `vsa_probe` confirms the needed sections (InstalledSoftware, LocalIpAddresses masks, appliedpolicies, patch policy SoftwareRules).

Still open from earlier phases (unchanged, external): VSA0-02/P0-02 host boot evidence, VSAP-01 vault (Entra dropped, DEC-03), VSAP-02 backup/restore drill on the host, VSAP-04 live pilot, VSAP-05 acceptance, VSA3-06 mail delivery (DEC-09), VSA5 group-move live validation (execution built, off by default), P3/P4 IT Glue/Autotask (out of Phase 1 scope, DEC-05).

