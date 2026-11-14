# LIST-01 - device lists, group navigation and saved layouts

User priority: Devices and group navigation; saved list layouts and faster filtering. The existing app is preserved. Baseline for this slice: ddaefa1. Implementation commit: fae7e6f. This slice does not declare the entire application finished.

## Problems reproduced and changes delivered

- The device page mixed nearly all filters, sorting, saved-view prompts and exports above a crowded eight-column table. The primary toolbar now contains search, site, last-seen state and export. Advanced filters and inline saved-view management are separate disclosures. Common quick filters and individually removable scope chips explain the active population.
- Site/group filters displayed IDs or labels without enough source context. Additive facet metadata now includes names and VSA source identity; selecting a group/site supplies its source ID. Device rows link to the source-qualified group. Existing legacy facet keys still work.
- Every keystroke requested a new server search. Typing is immediate and requests settle after 250 ms, with cancellation on changes/unmount. A visible updating state prevents navigation, selection and exports of stale displayed rows while replacements load. Ordinary whole-population exports still validate the current filters on the server.
- Visible columns were lost when filters/page/navigation remounted the table. Current columns, density and page size are now in the URL, preserving presentation when returning from a device. Server sorting uses accessible table headers, not a separate sort dropdown. Pagination adds bounded 25/50/100/200 sizes, first/last and direct page entry. Empty outdated pages retain recovery controls; a server-rejected page number also offers Return to first page without discarding filters.
- Saved views only stored filters and used browser prompt/confirm dialogs. The existing owner/customer-scoped API now stores validated visible columns, density and page size as well. Inline forms create private views by default, explicitly share with customer readers, update owned views and confirm deletion. Nonowners cannot alter shared views. CRUD is audited. Duplicate names now produce a validation error instead of a database exception/HTTP 500.
- Group navigation only offered a nested tree. A searchable directory is now the default, with source/site context, onboarding purpose, device totals and scoped device links. Search matches names, IDs, organization, site and source. Site/purpose filters and numeric/name sorting refine the authorized hierarchy already fetched; this is not a search over unseen vendor records. The hierarchy tab remains available.
- Healthy source status is compact on device/group pages. Freshness, source identity, fixture origin and sync access remain visible. Failed/stale/queued/unknown/quarantined sources expand to the full existing explanation.

Named saved layouts currently apply to devices. Other lists receive shared pagination/empty-state improvements, but their workflow redesign and persistent presentation are separate backlog items. Report schemas keep their defined export columns; hiding a list column does not change report fields or weaken export authorization.

## Storage, ownership and compatibility

Reporting migration 0003_saved_view_layout adds a JSON field with default {}. Runtime validation allows only supported device column IDs, compact/comfortable density and page sizes 25/50/100/200; arbitrary keys, duplicates, empty column lists and oversized/invalid values are rejected. Old filter-only saved views remain valid. Private/shared visibility and owner-only mutation remain enforced on the server. Layout/paging parameters are separated from population filters and are not sent as report filters.

Current presentation URLs contain field identifiers and the existing investigation filters; they do not grant access. Source/customer/object permissions are still checked by the API. No vendor adapter, endpoint, field, write permission, credential or remote telemetry integration was added.

## Verification

- Backend focused inventory/reporting run: 87 passed. Final full PostgreSQL suite: **603 passed in 356.42s**.
- Ruff check and format check: passed; Django check: no issues; makemigrations --check --dry-run: no changes; spectacular schema validation with --fail-on-warn: passed. No CI execution is claimed.
- Frontend full suite: **85 passed**, 20 files. TypeScript and ESLint: passed. Production build: passed; initial JS 343.57 KB / 107.81 KB gzip.
- Final complete browser suite: **40 passed (4.5 min)** in one isolated full run on the final source. Includes existing access denial, sync, exports, software/update intelligence, reconciliation and review workflows plus saved layout reload/paging/filter/device return, group-to-device source scoping and phone empty-result/keyboard recovery.
- Migration proof on an unused synthetic PostgreSQL database: reporting 0003 -> 0002 -> 0003 passed. The legacy view retained its ID, owner/customer and filters; the re-added layout defaulted to {}. Customer/user/asset counts remained unchanged. This is not a production backup/restore drill.
- Visual check: **34 screenshots**, 17 pages at 1440px and 390px, zero JavaScript errors and page-level horizontal overflow. Representative device/group screens were manually inspected. [Before/after gallery and logs](evidence/list-01/README.md).

Commands used: backend .venv/Scripts/ruff.exe check ., ruff.exe format --check ., manage.py check, manage.py makemigrations --check --dry-run, manage.py spectacular --file openapi.yaml --validate --fail-on-warn, .venv/Scripts/python.exe -m pytest -q --basetemp=var/codex-audit/pytest-lists-release --tb=line. Frontend npm.cmd run typecheck, npm.cmd run lint, npm.cmd run test -- --run --maxWorkers=2, npm.cmd run build, npx.cmd playwright test --output=../backend/var/codex-audit/lists-playwright-isolated. Visual capture: E2E_BASE_URL=<loopback preview> DEMO_USER_PASSWORD=<synthetic fixture password> node e2e/audit-review.mjs <output>.

The QA API uses an isolated synthetic database on loopback PostgreSQL port 56487, eager Celery, POSTGRES_CONN_MAX_AGE=0 and LOGIN_THROTTLE_RATE=1000/min only in its local process. Production defaults were not changed. Fixtures are labelled and no live customer credential was used.

## Failures found and corrected

The first frontend run had 8 failed / 70 passed: sparse facet fixtures exposed an undefined-array crash; hierarchy/chip tests still expected the former navigation; one unrelated connection UI test exceeded its wait while the machine was heavily loaded. Sparse fields now fail safely, hierarchy remains tested explicitly and final test concurrency is bounded. TypeScript/lint also caught test-only query options, a browser DOM reference and unnecessary non-null assertions; corrected.

An early full browser attempt exhausted the local database connection limit because multiple development previews had accumulated persistent connections. That attempt was stopped; only our identified fixture servers were stopped, and one nonpersistent local QA API was started on a fresh database. No database lock file or customer data was deleted.

A subsequent browser run had 37 passed / 3 failed. It reproduced navigation into an old search result during replacement loading, a column checkbox reverting briefly while its URL transition committed, and a mobile test selecting the hidden column checkbox instead of the visible Group combobox. Stale row actions are now inert during updates, checkbox feedback is immediate, and the accessibility locator identifies the correct control. Those three browser paths then passed. A later 39-pass/1-failure browser run typed characters individually and reproduced dropped search characters (DEMOA-WS001 became DM-1). The shared URL-filter hook now gives inputs immediate local state, recognizes its pending URL commits, and restores external back/forward navigation. The real sequential-keyboard path and both companion group/mobile scenarios passed after correction, including browser back navigation. The onboarding-purpose checkbox also needed immediate local feedback while mutation notifications committed; it now reverts on failure and invalidates directory purpose data after saving. That scenario passed after correction. A later full run completed all application assertions but a concurrent Playwright command deleted its trace output during context cleanup; final browser checks use one isolated output directory without concurrent browser commands. One unit test also needed to await the resulting request rather than only the preceding render. The new page-recovery mock initially rejected page 1 too; it was corrected to reject only out-of-range pages, and the actual mobile recovery path passed. A dedicated duplicate-name regression reproduced HTTP 500 and then passed after the constraint error was converted to validation. Initial fixture seeding omitted eager jobs and tried an unavailable local Redis; reseeding used eager jobs, without changing production configuration.

## Rollout and rollback

No deployment occurred. Apply reporting migration 0003 through the existing approved rollout before serving this backend revision; deploy matching frontend assets. The migration is additive and requires no vendor request or data backfill. Smoke-test a legacy filter-only view, private/shared ownership, saved presentation reload and scoped list/export parity.

Preferred rollback restores prior application images and retains the additive layout field/records. Reversing migration 0003 removes saved presentation data but retains the existing saved-view filters/ownership; archive preferences and approve that loss before a production schema rollback. Live VSA verification, Docker/AlmaLinux, production SSO/MFA, secrets/restore/load and independent security acceptance gates remain open.

Next product slice: simplify software and Windows-update investigation lists using the same focused controls. The first unchecked historical acceptance task remains P0-02 / VSA0-02 (Docker boot), blocked by the environment. No production-readiness claim is made.


## Main changed files

Backend: reporting/models.py and views.py; reporting migration 0003; inventory/views.py and hierarchy.py; openapi.yaml; tests/test_list_layouts.py. Frontend: DataTable.tsx, AssetsPage.tsx, SavedViews.tsx, DataSources.tsx, GroupsPage.tsx, GroupNetworkPage.tsx, useUrlFilters.ts, useDebouncedValue.ts, types.ts, index.css and focused tests. Browser: new z-list-usability.spec.ts; existing hierarchy test updated to explicitly choose Hierarchy; onboarding scenario renamed z-onboarding-groups.spec.ts so a full fresh-database suite syncs before it runs. Visual runner accepts a loopback base URL and optional view subset. Full path manifest: evidence/list-01/changed-files.txt.
