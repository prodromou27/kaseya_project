# VSA Phase 1 crosswalk: original tasks → VSA tasks

**Baseline:** commit `8056734`, audited 2026-11-13 (see `VSA_CURRENT_STATE.md`). The status legend comes from `docs/CLAUDE_CONTINUE_EXISTING_PROJECT.md`. **`DONE_VERIFIED` work is not redone.** "Verified" means automated tests on PostgreSQL plus fixture E2E. It never means live VSA, which is pending for every connector feature.

| VSA task | Original task(s) | Status | Existing files | Test proof | Remaining gap |
|---|---|---|---|---|---|
| VSA0-01 Repo, quality, CI | P0-01 | DONE_VERIFIED (local) | `backend/pyproject.toml`, `frontend/package.json`, `.github/workflows/*` | clean-clone runs at `5a6a6a4` and `8056734`; health endpoint tests | CI never executed (no remote) |
| VSA0-02 Compose dev/prod | P0-02 | PARTIAL | `compose.dev.yml`, `compose.prod.yml`, Dockerfiles, `infra/nginx/*` | YAML parse only | **Never booted** (no Docker host) |
| VSA0-03 Identity/RBAC | P0-03, P0-04, P0-05 | DONE_VERIFIED | `apps/accounts/*`, `apps/customers/*` | `test_auth.py`, `test_oidc.py`, `test_tenant_isolation.py` | Real Entra UAT is VSAP-01 |
| VSA0-04 Instance/scope/credential refs/mapping UI | P0-06, P1-03 | DONE_VERIFIED | `IntegrationInstance`, `CustomerSourceMapping`, `secrets.py`, `MappingsPanel.tsx` | `test_admin_api.py`, `test_sync.py` (quarantine) | — |
| VSA0-05 Audit, export authz, seeds | P0-07, P0-09 | DONE_VERIFIED | `apps/audit/*`, `apps/core/redaction.py`, `seed_demo` | `test_audit_and_errors.py`, `test_reports.py` | — |
| VSA1-01 API verification, connection test, rate budget, TLS, errors | P1-01 | DONE_VERIFIED (fixture, `5dbb567`) | `vsa/capabilities.json`, `http.py`, `integrations/views.py` (`test-connection`) | `test_vsa_adapter.py`, `test_connection_test.py`, `connection.test.tsx` | LIVE_VALIDATION_PENDING |
| VSA1-02 Adapter orgs/sites/groups/devices/assets | P1-01 | DONE_VERIFIED (fixture, `ea26682`) | `vsa/adapter.py` (assets, organizations, sites, groups, devices, asset detail) | `test_vsa_adapter.py`, `test_vsa1_hierarchy_network.py` | LIVE_VALIDATION_PENDING |
| VSA1-03 SyncRun/Generation/checkpoint/atomic publish | P1-02 | DONE_VERIFIED | `integrations/sync.py`, models | `test_sync.py` (26 tests) | — |
| VSA1-04 Observation schema: NIC/disks/software/agent/OS/security | P1-04, P1-05 | DONE_VERIFIED (fixture, `ea26682`) | `inventory/models.py`, `inventory/ingest.py`, `inventory/network.py`, `software/models.py` | `test_sync.py`, `test_p1_api.py`, `test_vsa1_hierarchy_network.py` | LIVE_VALIDATION_PENDING |
| VSA1-05 Device list/search/saved views/detail tabs | P1-04, P2-03 | PARTIAL | `inventory/views.py`, `AssetsPage.tsx`, `AssetDetailPage.tsx`, `SavedViews.tsx` | `test_p1_api.py`, `p1.test.tsx`, `vsa1.test.tsx`, `test_changes.py`, E2E | Notifications tab (VSA4-03) |
| VSA1-06 Customer > org > site > group explorer | — | DONE_VERIFIED (fixture, `ea26682`) | `inventory/hierarchy.py`, `GroupsPage.tsx` | `test_vsa1_hierarchy_network.py`, `vsa1.test.tsx`, E2E `vsa1.spec.ts` | LIVE_VALIDATION_PENDING |
| VSA2-01 Secure XLSX/CSV importer | — | DONE_VERIFIED (fixture, `dcecf60`) | `apps/onboarding/importer.py`, `OnboardingPage.tsx` | `test_onboarding.py`, `onboarding.test.tsx`, E2E `vsa2-onboarding.spec.ts` | Real customer layouts LIVE_VALIDATION_PENDING |
| VSA2-02 Deterministic matching + review | — | DONE_VERIFIED (fixture, `dcecf60`) | `apps/onboarding/matching.py`, `services.review` | `test_onboarding.py` (100-row fixture) | — |
| VSA2-03 Compare to pinned complete generation, history, unexpected set | — | DONE_VERIFIED (fixture, `dcecf60`) | `apps/onboarding/services.py`, migration `0002_customer_consistency` | `test_onboarding.py`, E2E | — |
| VSA2-04 Multi-tab XLSX/CSV export | P1-09, P2-04 | DONE_VERIFIED (fixture, `dcecf60`) | `apps/onboarding/workbook.py`, `render_xlsx_sheets` | `test_onboarding.py`, E2E download | — |
| VSA2-05 Group network view, CIDRs, duplicate IPs | — | DONE_VERIFIED (fixture, `ea26682` + `5dbb567`) | `inventory/hierarchy.py`, `network_views.py`, `GroupNetworkPage.tsx`, `ExpectedSubnets.tsx` | `test_vsa1_hierarchy_network.py`, `test_expected_subnets.py`, `network-review.test.tsx`, E2E `vsa2-network.spec.ts` | LIVE_VALIDATION_PENDING |
| VSA3-01 Catalog, aliases, comparator, approvals | P1-06, P1-07 | DONE_VERIFIED | `software/catalog.py`, `comparator.py` | `test_comparator.py` (32), `test_p1_api.py` | — |
| VSA3-02 Version classification dashboards, no false pending patch | P1-08 | DONE_VERIFIED | `software/queries.py`, `SoftwarePage.tsx` | `test_p1_api.py`, E2E p1 | — |
| VSA3-03 Available/installed OS updates | P2-01, P2-02 | DONE_VERIFIED | `apps/patching/*`, `WindowsUpdatesPage.tsx` | `test_patching.py` (21), E2E p2 | — |
| VSA3-04 Applied patch policies, definitions, drift | — | DONE_VERIFIED (fixture, `ff7a956`) | `patching/policies.py`, `policy_queries.py`, `policy_views.py`, `PatchPoliciesPage.tsx` | `test_patch_policies.py`, `policies.test.tsx`, E2E `vsa3-policies.spec.ts` | LIVE_VALIDATION_PENDING |
| VSA3-05 Report builder, 3 formats, saved filters, provenance, scoped downloads | P1-09, P2-03, P2-04, P2-06 | DONE_VERIFIED | `apps/reporting/*`, `ReportsPage.tsx` | `test_p2_reporting.py`, `test_reports.py`, E2E p2 | New reports for onboarding, network and policy as their data lands |
| VSA3-06 Schedules, mail only with approved policy | P2-05 | PARTIAL | `reporting/scheduling.py` | `test_p2_reporting.py` | Mail delivery is BLOCKED_APPROVAL (DEC-09); in-portal delivery is done |
| VSA3-07 Third-party pending/failed/reboot investigation | — | DONE_VERIFIED as explicit-unavailable (`ea26682`); live = BLOCKED_VENDOR | `software/capability.py`, `ThirdPartyPatchNotice.tsx` | `test_vsa1_hierarchy_network.py`, `vsa1.test.tsx`, E2E; docs evidence in `VSA_CURRENT_STATE.md` §3 | Live confirmation BLOCKED_VENDOR |
| VSA4-01 Agent health thresholds/cohorts | P2-02 (partly), RPT-06 | DONE_VERIFIED (fixture, `b345b8f`) | `inventory/health.py`, `health_views.py`, `DeviceHealthPage.tsx` | `test_device_health.py`, `health.test.tsx`, E2E `vsa4-health.spec.ts` | LIVE_VALIDATION_PENDING |
| VSA4-02 Hardware, disk, security tri-state | — | DONE_VERIFIED (fixture, `b345b8f`) | `inventory/health.py`, `vsa/schema.py` aggregates, R13/R14 | `test_device_health.py`, E2E | LIVE_VALIDATION_PENDING (field encodings) |
| VSA4-03 Notifications + approved custom fields | — | MISSING | — | — | — |
| VSA4-04 Snapshot diff | P2-06 (history only) | DONE_VERIFIED (fixture, `136ddb6`) | `inventory/changes.py`, `changes_views.py`, `ChangesPage.tsx`, R16 | `test_changes.py`, `changes.test.tsx`, E2E `vsa4-changes.spec.ts` | LIVE_VALIDATION_PENDING |
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
* **2026-11-13, `dcecf60`:** VSA2-01 through VSA2-04 are DONE_VERIFIED (fixture). Onboarding reconciliation is live in the portal against fixture data. Deviations are recorded in `ONBOARDING_RECONCILIATION.md` §Implementation notes. **Next: VSA3-04 (applied patch policies) and VSA4-01/02 (agent health, disks/security).** These also enable the `NO_PATCH_POLICY` and `OLD_AGENT` flags.
* **2026-11-13, `ff7a956`:** VSA3-04 is DONE_VERIFIED (fixture). The onboarding `NO_PATCH_POLICY` flag is now evaluated (explicit No Policy only), with logic `onboarding-match-2`. **Next: VSA4-01 (agent-health thresholds, old-agent baseline, which also enables `OLD_AGENT`) and VSA4-02 (disk thresholds, security tri-state views).**
* **2026-11-13, `b345b8f`:** VSA4-01 and VSA4-02 are DONE_VERIFIED (fixture). Onboarding `OLD_AGENT` is now evaluated against the approved minimum (logic `onboarding-match-3`). Every planned execution step (1–5) is now complete. **Remaining P0/P1 gaps:** VSA1-01 connection test (`/ratelimits`); VSA1-05 notifications/reconciliation tabs; VSA2-05 expected-subnet policy; VSA4-03 notifications; VSA4-04 generation diff; VSAP-02 backups; VSAP-03 SAST/threat review. Docker/CI boot and the live pilot remain blocked by environment and approvals.
* **2026-11-13, `5dbb567`:** VSA1-01 and VSA2-05 are DONE_VERIFIED (fixture). **Remaining:** VSA1-05 (notification and reconciliation tabs), VSA4-03 (notifications), VSA4-04 (generation diff), VSA4-05/06, VSAP-02/03/05. Docker/CI boot, live pilot (VSAP-04) and moves (VSA5) stay blocked.
* **2026-11-13, `136ddb6`:** VSA4-04 is DONE_VERIFIED (fixture). VSA1-05 gained the Onboarding (reconciliation) tab; only notifications remain. **Remaining:** VSA4-03 (+ VSA1-05 notifications tab), VSA4-05 (lifecycle catalog), VSA4-06 (100k performance), VSAP-02/03/05. Docker/CI boot, live pilot (VSAP-04) and moves (VSA5) stay blocked.
