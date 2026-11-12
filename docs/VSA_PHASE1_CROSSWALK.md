# VSA Phase 1 crosswalk: original tasks → VSA tasks

**Baseline:** commit `8056734`, audited 2026-11-13 (see `VSA_CURRENT_STATE.md`). The status legend comes from `docs/CLAUDE_CONTINUE_EXISTING_PROJECT.md`. **`DONE_VERIFIED` work is not redone.** "Verified" means automated tests on PostgreSQL plus fixture E2E. It never means live VSA, which is pending for every connector feature.

| VSA task | Original task(s) | Status | Existing files | Test proof | Remaining gap |
|---|---|---|---|---|---|
| VSA0-01 Repo, quality, CI | P0-01 | DONE_VERIFIED (local) | `backend/pyproject.toml`, `frontend/package.json`, `.github/workflows/*` | clean-clone runs at `5a6a6a4` and `8056734`; health endpoint tests | CI never executed (no remote) |
| VSA0-02 Compose dev/prod | P0-02 | PARTIAL | `compose.dev.yml`, `compose.prod.yml`, Dockerfiles, `infra/nginx/*` | YAML parse only | **Never booted** (no Docker host) |
| VSA0-03 Identity/RBAC | P0-03, P0-04, P0-05 | DONE_VERIFIED | `apps/accounts/*`, `apps/customers/*` | `test_auth.py`, `test_oidc.py`, `test_tenant_isolation.py` | Real Entra UAT is VSAP-01 |
| VSA0-04 Instance/scope/credential refs/mapping UI | P0-06, P1-03 | DONE_VERIFIED | `IntegrationInstance`, `CustomerSourceMapping`, `secrets.py`, `MappingsPanel.tsx` | `test_admin_api.py`, `test_sync.py` (quarantine) | — |
| VSA0-05 Audit, export authz, seeds | P0-07, P0-09 | DONE_VERIFIED | `apps/audit/*`, `apps/core/redaction.py`, `seed_demo` | `test_audit_and_errors.py`, `test_reports.py` | — |
| VSA1-01 API verification, connection test, rate budget, TLS, errors | P1-01 | PARTIAL | `vsa/capabilities.json`, `http.py` | `test_vsa_adapter.py` (50 tests) | No connection-test action (`/ratelimits`); capability record lacks devices/sites/groups/policies |
| VSA1-02 Adapter orgs/sites/groups/devices/assets | P1-01 | DONE_VERIFIED (fixture, `ea26682`) | `vsa/adapter.py` (assets, organizations, asset detail) | `test_vsa_adapter.py` | **`/sites`, `/groups`, `/devices` missing**; no group ID |
| VSA1-03 SyncRun/Generation/checkpoint/atomic publish | P1-02 | DONE_VERIFIED | `integrations/sync.py`, models | `test_sync.py` (26 tests) | — |
| VSA1-04 Observation schema: NIC/disks/software/agent/OS/security | P1-04, P1-05 | DONE_VERIFIED (fixture, `ea26682`) | `inventory/models.py`, `software/models.py` | `test_sync.py`, `test_p1_api.py` | **NIC/IP/MAC, disks, security discarded** |
| VSA1-05 Device list/search/saved views/detail tabs | P1-04, P2-03 | PARTIAL | `inventory/views.py`, `AssetsPage.tsx`, `AssetDetailPage.tsx`, `SavedViews.tsx` | `test_p1_api.py`, `p1.test.tsx`, E2E | No MAC/IP search; no network/hardware/security tabs |
| VSA1-06 Customer > org > site > group explorer | — | DONE_VERIFIED (fixture, `ea26682`) | — | — | everything |
| VSA2-01 Secure XLSX/CSV importer | — | MISSING | (openpyxl present) | — | everything |
| VSA2-02 Deterministic matching + review | — | MISSING | — | — | everything |
| VSA2-03 Compare to pinned complete generation, history, unexpected set | — | MISSING | (pinned generations exist) | — | everything |
| VSA2-04 Multi-tab XLSX/CSV export | P1-09, P2-04 | PARTIAL | `reporting/renderers.py` (single data sheet) | `test_p2_reporting.py` | multi-sheet workbook |
| VSA2-05 Group network view, CIDRs, duplicate IPs | — | PARTIAL (`ea26682`) | — | — | depends on VSA1-04 network data |
| VSA3-01 Catalog, aliases, comparator, approvals | P1-06, P1-07 | DONE_VERIFIED | `software/catalog.py`, `comparator.py` | `test_comparator.py` (32), `test_p1_api.py` | — |
| VSA3-02 Version classification dashboards, no false pending patch | P1-08 | DONE_VERIFIED | `software/queries.py`, `SoftwarePage.tsx` | `test_p1_api.py`, E2E p1 | — |
| VSA3-03 Available/installed OS updates | P2-01, P2-02 | DONE_VERIFIED | `apps/patching/*`, `WindowsUpdatesPage.tsx` | `test_patching.py` (21), E2E p2 | — |
| VSA3-04 Applied patch policies, definitions, drift | — | MISSING | — | — | everything (routes verified in docs) |
| VSA3-05 Report builder, 3 formats, saved filters, provenance, scoped downloads | P1-09, P2-03, P2-04, P2-06 | DONE_VERIFIED | `apps/reporting/*`, `ReportsPage.tsx` | `test_p2_reporting.py`, `test_reports.py`, E2E p2 | New reports for onboarding, network and policy as their data lands |
| VSA3-06 Schedules, mail only with approved policy | P2-05 | PARTIAL | `reporting/scheduling.py` | `test_p2_reporting.py` | Mail delivery is BLOCKED_APPROVAL (DEC-09); in-portal delivery is done |
| VSA3-07 Third-party pending/failed/reboot investigation | — | DONE_VERIFIED as explicit-unavailable (`ea26682`); live = BLOCKED_VENDOR | — | docs evidence in `VSA_CURRENT_STATE.md` §3 | Explicit unavailable UI missing; live confirmation BLOCKED_VENDOR |
| VSA4-01 Agent health thresholds/cohorts | P2-02 (partly), RPT-06 | PARTIAL | offline filter, `stale_devices` report | `test_p2_reporting.py` | thresholds, old-agent, cohort denominators |
| VSA4-02 Hardware, disk, security tri-state | — | MISSING | — | — | depends on VSA1-04 |
| VSA4-03 Notifications + approved custom fields | — | MISSING | — | — | — |
| VSA4-04 Snapshot diff | P2-06 (history only) | PARTIAL | `reporting/trends.py`, asset history | `test_p2_reporting.py` | generation-to-generation diff |
| VSA4-05 Lifecycle catalog | — | MISSING | — | — | — |
| VSA4-06 Performance / 100k load | — | MISSING | — | — | — |
| VSA5-01..04 Device move | — | BLOCKED_APPROVAL | — | — | Must stay disabled; design only when approved |
| VSAP-01 SSO/MFA, TLS, vault, SSRF | P5-01, P5-02 | PARTIAL | OIDC (mock IdP), SSRF/TLS controls | `test_oidc.py`, `test_vsa_adapter.py` | Real Entra and vault are BLOCKED_APPROVAL (DEC-03/07) |
| VSAP-02 Backups/restore | P5-03, P5-04 | MISSING | — | — | — |
| VSAP-03 Threat review, SAST/dep scan, IDOR regression | P5-07 | PARTIAL | `security.yml`, IDOR suites | pip-audit/npm audit clean | SAST and threat review |
| VSAP-04 Live pilot | P5-08 | BLOCKED_VENDOR | — | — | Needs token and pilot customer (DEC-04/10) |
| VSAP-05 Final acceptance | P5-09 | MISSING | — | — | — |

Deferred, not prioritised: P3-* (IT Glue) and P4-* (Autotask). No code exists for either.

## Execution order chosen

These follow the dependency order from the P0 priorities in `PHASE1_SCOPE.md` and `PHASE1_IMPLEMENTATION_PLAN.md`:

1. **VSA1-02 / VSA1-04 / VSA1-06 (hierarchy and network foundation):** collect `/sites`, `/groups` and `/devices` (group ID, agent installed); keep NICs/IPs, disks and security; build the org > site > group explorer.
2. **VSA2-05:** group network view (derived CIDRs, duplicate IP/MAC review flags). The data from step 1 makes this cheap.
3. **VSA3-07:** explicit "third-party deployment status unavailable" panel, recorded with docs evidence.
4. **VSA2-01..04:** Excel/CSV onboarding reconciliation with a multi-tab workbook.
5. **VSA3-04:** applied patch policies; **VSA4-01/02:** agent health and disks/security.

Each step's evidence is recorded in `docs/IMPLEMENTATION_EVIDENCE.md`, and the status in this table is updated only after tests pass.

## Progress log

* **2026-11-13, `ea26682`:** VSA1-02, VSA1-04 and VSA1-06 are DONE_VERIFIED (fixture). VSA2-05 is PARTIAL: expected-subnet policy and threshold flags remain. VSA3-07 is DONE_VERIFIED as explicit-unavailable. VSA1-05 gained MAC/IP search and Network and Hardware & security tabs, but stays PARTIAL until the policy, notification and reconciliation tabs exist. **Next: VSA2-01..04 (Excel onboarding reconciliation).**
