# Codex implementation and verification — 2026-11-14

This is a working-code improvement to the existing application, based on clean baseline `595d3e3`. No rebuild, production deployment, live vendor request, real customer credential or unrelated integration was introduced. Local fixture data is visibly labelled.

## Completed slices

| Task IDs | Problem and result | Main changed files |
|---|---|---|
| CX-00 | Audited the existing implementation, tests, migrations, deployment files and actual screens; recorded prioritized gaps | CODEX_APPLICATION_AUDIT.md, CODEX_FUNCTIONAL_GAP_ANALYSIS.md, CODEX_REMEDIATION_BACKLOG.md, CODEX_UI_UX_REDESIGN.md |
| CX-01 | Lists/exports diverged and navigation lost filters. Shared validated filters now cover source-ID/IP/MAC search, scope, sort, offline cutoff and selected devices; URL pages and column selection support investigation | inventory/filters.py, inventory/views.py, reporting/registry.py, reporting/views.py; AssetsPage.tsx, DataTable.tsx, useUrlFilters.ts; test_p1_api.py |
| CX-02/CX-06 | Hidden workflows and narrow-screen overflow. Grouped/searchable navigation, explicit customer scope, device search, responsive shared controls/tabs, bounded table scrolling, grouped detail workspace and recovery boundary | AppShell.tsx, App.tsx, index.css, ui.tsx, Tabs.tsx, DataTable.tsx, AppErrorBoundary.tsx, AssetDetailPage.tsx |
| CX-03/CX-04 | Dashboard used single-source history as current totals, hid failures and linked unfiltered destinations. Uses current customer summaries, exact health/software/severity drilldowns, visible freshness/errors, persistent filters and direct device links | KpiTiles.tsx, DashboardPage.tsx, DataSources.tsx, DeviceHealthPage.tsx, SoftwarePage.tsx, WindowsUpdatesPage.tsx; dashboard/health tests |
| CX-05 | Unclear onboarding progress and stale preview controls. Added progression and mapping-validation feedback; comparison is disabled during revalidation. Preserved the customer-first secure upload and deterministic matcher | OnboardingPage.tsx; existing onboarding backend/E2E tests |
| CX-07 | Group/site IDs merged across sources; group-network export was absent. Composite source keys, qualified links, ambiguous-ID refusal, safe legacy subnet rules and pinned R10 CSV/XLSX/PDF export | hierarchy.py, GroupNetworkPage.tsx, GroupsPage.tsx, reporting/registry.py; test_inventory_remediation.py |
| CX-08 / VSA4-06 bounded fixture | 100k-device health summary was slow. Compact streamed scalar aggregation preserves classifications and avoids full detailed-object construction. Route chunks also reduce initial JS transfer | health.py, benchmark_inventory.py, App.tsx; test_device_health.py, CODEX_PERFORMANCE.md |
| CX-09 / VSA5-02 internal only | Group-change review was missing. New customer-scoped immutable proposals, explicit role capabilities, expiry, independent review, safe replay and audit. No execute route or vendor writes | roles.py, models.py, moves.py, move_views.py, urls.py, inventory migrations 0009/0010, GroupMovesPage.tsx; test_group_moves.py |

Full changed-file manifest: CODEX_CHANGED_FILES.txt. Backend paths in the table are relative to `backend/apps/`; frontend paths are under `frontend/src/`. API schema: `backend/openapi.yaml`.

## Local delivery commits

- `c2e7c4e`: baseline audit, redesign scope, functional gaps and prioritized backlog.
- `f4cfab1`: tested backend/frontend implementation, migrations, OpenAPI and regression/browser tests.
- Retained evidence, operator documentation and task status are delivered in the following documentation commit. No push or CI run is claimed.

## Final check evidence

Python commands use `backend/.venv/Scripts/` with Python 3.12.10. Node 24.22.2 and npm 11.19.1 use the existing installed dependencies. PostgreSQL 16.2 runs in a new ignored fixture directory on loopback port **56487**; application and test databases are separate. No SQLite substitution.

| Command (run in indicated directory) | Outcome |
|---|---|
| `backend: .venv/Scripts/ruff.exe check .` | All checks passed |
| `backend: .venv/Scripts/ruff.exe format --check .` | 176 files already formatted |
| `backend: .venv/Scripts/python.exe manage.py check` | No issues |
| `backend: .venv/Scripts/python.exe manage.py makemigrations --check --dry-run` | No changes detected |
| `backend: .venv/Scripts/python.exe manage.py spectacular --file openapi.yaml --validate --fail-on-warn` | Exit 0, no warnings |
| `backend: .venv/Scripts/python.exe -m pytest -q --basetemp=var/codex-audit/pytest-complete --tb=line` | **585 passed in 91.73 s** |
| `frontend: npm.cmd run test -- --run` | **74 passed**, 18 files |
| `frontend: npm.cmd run typecheck` | Exit 0 |
| `frontend: npm.cmd run lint` | Exit 0 |
| `frontend: npm.cmd run build` | Exit 0; initial JS **342.30 KB / 107.62 KB gzip**, formerly about 576 KB |
| `frontend: npx.cmd playwright test` | **36 passed in 2.5 min** on a fresh fixture database, including the network-export test |
| `frontend: npx.cmd playwright test e2e/z-codex-workflows.spec.ts --grep 'group network exports'` | **1 passed**, actual CSV download with source/provenance fields |
| `frontend: npx.cmd playwright test e2e/p2.spec.ts --grep 'unauthorised recipient'` | **1 passed** after making the test definition name unique for repeat runs |
| Post-layout investigation/report subset | Eight paths passed; the reused schedule fixture produced duplicate-name selector ambiguity, fixed and rerun separately above |
| `frontend: node e2e/audit-review.mjs <output>` | 34 final desktop/phone screens, no JavaScript errors or page-level overflow; see retained observations |
| `backend: manage.py benchmark_inventory --measure-existing --confirm-fixture-only` | Same **100,000-device** fixture: health summary **16.3327 → 1.2915 s**, 9 queries; detailed limitations in CODEX_PERFORMANCE.md |
| `backend: manage.py migrate inventory 0008 --noinput`, then `migrate inventory --noinput` | Both directions passed in disposable benchmark DB; **100,000 assets retained**, new proposal table recreated empty |
| `npm.cmd audit --json` | 0 vulnerabilities |
| `uvx --offline --python 3.12 pip-audit --strict --disable-pip -r backend/requirements.lock` | Exit 0, no known vulnerabilities |
| `uvx --offline bandit -q -r backend/apps backend/config -ll` | Exit 0, no medium/high findings |
| `manage.py check --deploy --fail-level ERROR` (dummy production config) | Exit 0; existing proxy-redirect warning security.W008 |
| `uvx --offline --from shellcheck-py shellcheck -S warning ...` | Exit 0 for the five deployment/backup scripts |
| `git diff --check` | Clean |

Environment for fixture QA: POSTGRES_HOST=127.0.0.1, POSTGRES_PORT=56487, dedicated fixture/test database names, CELERY_TASK_ALWAYS_EAGER=true, REQUIRE_SECOND_APPROVER=true. Repeated Playwright logins use LOGIN_THROTTLE_RATE=1000/min **only in the local QA process**; production defaults are unchanged. Synthetic demo-password value is not needed in retained reports. `--offline` on uvx resolves cached tooling; dependency advisory checks still query their advisory services.

Actual logs and baseline/after screenshots: [evidence directory](evidence/codex-2026-11-14/README.md). Ordinary functional QA does not satisfy the separate independent security audit requirements; see CODEX_SECURITY_REVIEW.md.

## Intermediate failures and corrections

- Initial Vitest invocation failed in esbuild path resolution because the filesystem sandbox denied parent-directory reads; rerunning with the restriction lifted passed.
- Initial PostgreSQL tests could not connect. Found existing local binaries, created an isolated cluster; port 55432 was occupied, so used 56487. The cached package lacked timezone files; supplied the locally installed tzdata files in a workspace-only copy. Pytest then needed an explicit workspace basetemp because its old global temp directory was inaccessible.
- An intermediate broad import replacement caused an indentation error: first regression run **10 failed / 545 passed**. Corrected it, then restored the unchanged backend baseline for **555 passed**, followed by the final complete regression above.
- Baseline browser run **22 passed / 9 failed** due to repeated-log-in throttling and restarting the fixture API during that attempt. Final expanded uninterrupted fresh-fixture run **36 passed**.
- Frontend expectations were updated for intentional navigation/drilldown changes; TypeScript caught a test-only unsupported `exact` option and an incorrect preview-field assumption, both fixed.
- Browser testing found real return-filter loss on tab navigation; moved return filters into the URL. It also found an imprecise severity label; replaced it with an explicitly associated Field. Existing search locators were made exact after adding scoped header search.
- A later browser run **30 passed / 5 failed** (three ambiguous legacy search locators, severity label and return-filter persistence); fixed all, then the full 35-test run passed. Three targeted investigation/mobile cases passed separately.
- Re-running schedule creation on an already-used fixture created duplicate display names; the test now creates a unique name and scopes its form exactly. The schedule authorization path passed after correction.
- Ruff caught line length/format errors during edits; final checks pass. One npm command was invoked from the repository root (no package.json); rerun in frontend passed.
- Benchmark fixture initially omitted collected_at and rolled back; first measurement then needed localhost as its request Host. Fixed both; retained the synthetic 100k fixture for direct before/after measurement.
- Earlier production build reported a >500 KB chunk. Route splitting removed that warning; no dependency was added.

## Vendor/API status and acceptance boundaries

- Official public API reference re-opened: https://api.vsax.net/ on 2026-11-14. Existing GET-only adapter routes remain **fixture-tested**. No new vendor endpoint or field was implemented in this remediation.
- https://help.vsa10.kaseya.com/ returned 404 through the research tool. Installed tenant/version and live field-level accuracy remain **unverified** here.
- Third-party patch applicability/deployment, failed-update/reboot state remain **unavailable pending authoritative capability evidence**; software version comparison is kept separate.
- Group moves are **internal proposal/review only**. Execution, write credentials, real readback and authorized pilot remain gated.
- Docker/AlmaLinux boot, real SSO/MFA, vault/key custody, target-host restore/concurrency and independent security review remain external gates. CI was not run by this session.
- Additional UI refinements remain explicitly listed in CODEX_REMEDIATION_BACKLOG.md; the entire wish list or production readiness is not declared complete.
