# LIST-02 - software and Windows-update investigation

Baseline: `2cc5998` (LIST-01). Implementation: `7a6df23`. This bounded continuation simplifies the next two investigation workspaces. It does not finish the whole application or close production gates.

## Delivered behavior

- Software separates Overview, Installations and Exceptions. Overview has a product finder and classification/product drilldowns. Installation search matches product name, publisher, version and device hostname. Existing comparison denominators, exception permissions and third-party patch limitations remain visible.
- Windows updates separates Update records, Collection coverage and Common updates. Common KB links open the matching available records. Record search matches title, KB and device hostname. Coverage search matches hostname/source device ID, independently of update-record filters.
- The old coverage request fetched at most 200 devices with no navigation. Coverage now pages the complete authorized population with 25/50/100/200 page sizes and first/last/direct page controls. Missing counts display Unknown; source device type and OS remain separate evidence.
- Software installations, exceptions and update records retain full pagination. Installation and record column choosers retain their local choices during paging. Named server-persisted layouts still apply to Devices; extending them to other workspaces is LIST-04.
- Searches settle after 250 ms. URL state survives reload/navigation; old displayed rows cannot be activated while replacements load. Invalid pages offer a first-page recovery action. Loading, empty and error states use the existing shared boundaries.
- Device links open the relevant Software or OS updates tab. The back link preserves the investigation filters/page. Return targets are restricted to the two internal workspace paths; object/customer access is checked by the existing API.
- Export installations and Export update records share search helpers with their pinned report queries. Export device coverage is a separate CSV/XLSX/PDF report (`os_update_coverage`), with one device per row, explicit collection states, nullable counts, source instance/generation/as-of and source device type. The existing export capability, protected storage, audit, retention and renderers apply. Hiding a list column does not change a report schema.

Summary tiles describe the whole current customer snapshot. Filters apply to the active table; exports use that table's population filters, not the current page. Update-record and device-coverage exports are deliberately labelled by their different populations. Collection states do not establish patch installation failure, reboot need or third-party missing-patch applicability. Unknown, unsupported, failed and not collected are never converted to zero.

## Architecture and compatibility

No model or schema migration is needed. Current lists and pinned exports reuse the same normalized search predicates, with customer/generation scope established by their callers. Existing report types keep their schemas. The new coverage report is additive. Report filters are validated; source IDs and snapshot publication timestamps provide provenance without inventing vendor scan times.

No connector endpoint, vendor field, vendor write, real credential or telemetry integration was added. Existing read-only connector capabilities were not revalidated live. New behaviors are fixture-tested only; live verification remains unavailable pending an approved pilot.

Main source paths: backend apps/software/queries.py, apps/patching/queries.py, apps/reporting/registry.py, openapi.yaml and tests/test_list_intelligence.py; frontend SoftwarePage.tsx, WindowsUpdatesPage.tsx, InvestigationDeviceLink.tsx, AssetDetailPage.tsx, focused UI tests and e2e/z-intelligence-lists.spec.ts. The visual runner adds explicit installation and coverage routes. A full changed-file manifest accompanies the evidence.

## Acceptance and commands

Final acceptance results and terminal logs are retained in [the evidence gallery](evidence/list-02/README.md). Backend full-suite verification preceded the final restoration of the coverage device-type column; all 11 feature cases were rerun after that change. Frontend and browser acceptance use the final source.

- Full PostgreSQL suite: **614 passed in 217.72s**; final feature rerun: **11 passed in 47.06s**.
- Frontend: **89 passed in 21 files**; TypeScript, ESLint and production build passed. Initial JavaScript: 343.67 KB / 107.86 KB gzip.
- Full browser suite on a fresh fixture database: **43 passed (4.4 minutes)**, including all existing scenarios and the three new investigation paths.
- Visual capture: **8 screenshots** at 1440px/390px, zero JavaScript errors and page-level overflow. Desktop software/installation and phone coverage/update-record screens inspected.
- Ruff check/format (180 files), Django checks, migration drift and OpenAPI validation with --fail-on-warn passed. No migration required.

Backend commands (from backend):

```powershell
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py spectacular --file openapi.yaml --validate --fail-on-warn
.venv/Scripts/python.exe -m pytest -q --basetemp=var/codex-audit/pytest-intelligence-full --tb=line
.venv/Scripts/python.exe -m pytest tests/test_list_intelligence.py -q --basetemp=var/codex-audit/pytest-intelligence-final --tb=line
```

Frontend commands (from frontend):

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run test -- --run --maxWorkers=2
npm.cmd run build
npx.cmd playwright test --output=../backend/var/codex-audit/intelligence-verified-traces
node e2e/audit-review.mjs ../backend/var/codex-audit/intelligence-screens
```

The database is an isolated synthetic PostgreSQL fixture on loopback port 56487. Full browser acceptance starts from a new migrated/seeded database, not a customer environment. Its local API uses eager Celery, POSTGRES_CONN_MAX_AGE=0 and LOGIN_THROTTLE_RATE=1000/min; production defaults are unchanged. Browser/visual commands set E2E_BASE_URL to the loopback preview and DEMO_USER_PASSWORD to a synthetic-only value. Visual capture selects software,software-installations,windows-updates,update-coverage via AUDIT_VIEWS. No CI execution or production deployment is claimed.

Coverage includes searched list/export parity; a 205-device population across three pages; CSV/XLSX/PDF; explicit unknown counts; cross-customer API/download denial; malformed filters; immutable pinned output after a subsequent sync; coverage error/paging/empty states; product search recovery; sequential typing and device return; filtered downloaded coverage; plus the existing application browser scenarios.

## Failures found and resolved

Early new backend tests misread quoted CSV provenance lines and the initial queued report response, and compared formula-escaped hostile fixture hostnames literally (8 failed/30 passed, then 5 failed/6 passed). The test parser now uses CSV records and authorized device IDs; completed report assertions use the database run. No production escaping was weakened. TypeScript also caught a missing coverage-status default, corrected in the component owning that state.

The first new Windows browser path assumed a particular device had an available update. It correctly had none; the scenario now selects a device from actual reported records. The first full browser run passed 42/43 and caught the dropped raw device-type column in coverage. The column was restored in UI and the new export, with a frontend regression assertion; the final complete suite was rerun. Initial attempts/results remain recorded separately from the final pass. Browser commands run sequentially with unique output directories to avoid trace cleanup conflicts.

## Rollout, rollback and remaining work

Deploy frontend/backend together using the existing reviewed deployment process; smoke-test searched list/export parity, a device return link and coverage paging. No migration, backfill or vendor request is required for this slice. Before rolling back to a registry without os_update_coverage, pause its schedules and archive/manage its report definitions; preserve generated artifacts, runs and audit records. Existing report definitions and snapshot data remain compatible.

Next product slice: LIST-03, clearer guided Excel reconciliation and review/result actions. LIST-04 retains named presentation for other lists and report branding/mobile refinements. Historical P0-02/VSA0-02 Docker acceptance remains open, as do approved AlmaLinux/SSO/MFA/secrets/restore/load/security/live-pilot gates. This local fixture evidence cannot close those gates.
