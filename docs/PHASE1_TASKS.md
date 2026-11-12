# Phase 1 backlog — VSA X ONLY

**Initial status:** all tasks unchecked in this documentation package. Check only after actual implementation + tests. Log commit/test evidence per task in `docs/IMPLEMENTATION_EVIDENCE.md`.

## VSA0 — Foundation

- [ ] **VSA0-01 [P0]** Inspect repo; build monorepo (Django/React/TS), pinned dependencies, lint/typing, Git CI. AC: checks/build/health endpoint pass.
- [ ] **VSA0-02 [P0]** Dev/prod Compose, PostgreSQL, Redis, Celery, proxy, nonroot containers, health & `.env.example`. AC: clean demo boot; DB/Redis not publicly exposed.
- [ ] **VSA0-03 [P0]** User/customer/membership/role, authorization service, bootstrap admin + OIDC-ready. AC: anonymous/foreign-customer routes denied.
- [ ] **VSA0-04 [P0]** IntegrationInstance, CustomerVsaScope, protected credential refs, admin mapping UI. AC: unknown org quarantined.
- [ ] **VSA0-05 [P0]** Immutable audit events, access changes, export authorization, protected demo seeds. AC: redaction/IDOR tests.

## VSA1 — Inventory + groups

- [ ] **VSA1-01 [P0]** Verify official API and capability matrix, connection test, rate-limit budget, TLS, error handling. AC: fixture and invalid-token cases.
- [ ] **VSA1-02 [P0]** Adapter: organizations/sites/groups/devices/assets, include sections, paging, stable ID link. AC: source fixture contracts.
- [ ] **VSA1-03 [P0]** SyncRun/Generation/checkpoint; atomic publish, partial state, quarantine and stale flag. AC: restart/429/partial tests.
- [ ] **VSA1-04 [P0]** Asset and detailed observation schema, NIC/disks, software, agent, OS and security. AC: migrations and multi-NIC tests.
- [ ] **VSA1-05 [P0]** Device list/search/saved views & detailed tabs, source provenance, scoped UI. AC: frontend+API tests.
- [ ] **VSA1-06 [P0]** Customer > org > site > group explorer with counts and status. AC: scoped tree; names not global keys.

## VSA2 — Excel, network

- [ ] **VSA2-01 [P0]** Secure XLSX/CSV importer, sheet selection/mapping/template/preview. AC: malicious/big/formula upload tests.
- [ ] **VSA2-02 [P0]** Deterministic match engine and classifications, human review; invalid/duplicate/ambiguous. AC: 100-row fixture matches totals.
- [ ] **VSA2-03 [P0]** Compare against pinned complete VSA generation, history, inverse unexpected set. AC: stale/incomplete/cross-customer blocked.
- [ ] **VSA2-04 [P0]** Multi-tab XLSX and CSV export; filtering; private artifact retention. AC: correct row totals, formula safety.
- [ ] **VSA2-05 [P0]** Group network view, derived CIDRs, duplicate IP review and threshold flags. AC: dual-stack/multi-NIC/virtual NIC tests.

## VSA3 — Patch/software/reporting

- [ ] **VSA3-01 [P0]** Reviewed software catalog, aliases/edition/channel, version comparator and admin approvals. AC: non-standard version tests.
- [ ] **VSA3-02 [P0]** Version classification and device/product dashboards with unknown/excluded. AC: no false pending patch.
- [ ] **VSA3-03 [P0]** Available/installed **OS** updates in device and customer views, report definitions. AC: missing/empty/stale not conflated.
- [ ] **VSA3-04 [P1]** Applied patch policies, policy definitions and expected-policy drift. AC: no-policy vs unknown vs applied.
- [ ] **VSA3-05 [P0]** Report builder, CSV/XLSX/PDF, saved filters, source provenance, scoped artifact downloads. AC: totals/reproducibility/security.
- [ ] **VSA3-06 [P1]** Scheduled reports, mail delivery only with approved recipient policy; async status/history. AC: no cross-customer recipient leak.
- [ ] **VSA3-07 [GATED]** Investigate actual third-party patch pending/failed/reboot statuses and Advanced Reporting supported API/export. AC: recorded source evidence OR explicit unavailable UI.

## VSA4 — Deep operations

- [ ] **VSA4-01 [P1]** Agent health thresholds, offline/old version/stale, complete cohort denominators. AC: source timestamps.
- [ ] **VSA4-02 [P1]** Hardware, disk threshold, security status tri-state. AC: not-live telemetry clearly labelled.
- [ ] **VSA4-03 [P1]** Notifications + approved custom fields; sensitive-field allowlist. AC: audit/PII minimization.
- [ ] **VSA4-04 [P1]** Historical snapshot diff: group/IP/software/agent/OS changes. AC: no fabricated actor/time.
- [ ] **VSA4-05 [P2]** Software/OS lifecycle catalog + sources/end dates; confidence. AC: unverified entries unknown.
- [ ] **VSA4-06 [P2]** Performance, 100k asset load fixture, sync health, cache/indexes. AC: documented load and query results.

## VSA5 — Exceptional write path, disabled by default

- [ ] **VSA5-01 [GATED]** Separate action permission model, feature flag + vaulted write credential and signed independent owner approval. AC: defaults OFF.
- [ ] **VSA5-02 [GATED]** Propose/approve state machine with immutable diff, policy impact, expiry, no self approval. AC: cross-customer denied.
- [ ] **VSA5-03 [GATED]** One documented device move PUT, durable attempt, readback, unknown outcome and audit. AC: timeout no double PUT.
- [ ] **VSA5-04 [GATED]** Authorized pilot and readback acceptance. AC: written approval and evidence; bulk move remains disabled.

## VSAP — Operational readiness

- [ ] **VSAP-01 [P0]** Entra OIDC/MFA and roles, TLS/cookies, secrets vault/rotation and SSRF protection validated.
- [ ] **VSAP-02 [P0]** PostgreSQL backups + encrypted off-host copies + isolated restore evidence, retention and secure reports.
- [ ] **VSAP-03 [P0]** Threat review, SAST/dependency scan, security/IDOR/tenant regression tests, deployment runbooks.
- [ ] **VSAP-04 [P0]** Approved VSA pilot with representative data, cross-check with VSA UI, API capability sign-off.
- [ ] **VSAP-05 [P0]** Final acceptance checklist, reports/coverage/recovery/reliability metrics and runbook handoff.

**Not included in this phase:** IT Glue, PSA, Tenable, MCP, scripts/patching/reboots, bulk moves, VSA policy editing or source DB queries.
