# Phase P2 acceptance record: Windows updates, reports, history

**Status:** P2-01 to P2-06 are implemented and tested against **fixtures only**. **P2-07 (the reporting gate) is open.** It depends on the P0 and P1 gates (Docker boot, CI run, sign-off), on an approved live pilot, and on a reporting-owner review of report layouts and metric definitions (DEC-08, DEC-09).

| Field | Value |
|---|---|
| Git revision | `c483a8f` on `main` (local repository; no remote, no CI run) |
| Date | 2026-11-13 |
| Environment | Windows 11, Python 3.12.10, Node 24.22, PostgreSQL 16.2 (local disposable cluster). No Docker, no Redis (Celery eager; Beat is exercised by calling its dispatcher directly) |
| Data basis | Synthetic tests and the fictional `seed_demo` tenant. Its KB numbers (5099xxx) and update titles are invented. **No live VSA X calls.** |

## Vendor API verification (VSA X OS update sections)

These were re-read from <https://api.vsax.net/> on 2026-11-12 and recorded in `apps/integrations/vsa/capabilities.json` → `os_update_fields`.

| Fact | Status |
|---|---|
| `Updates` = object of counts by severity (example: `Critical`, `Important`, `Unspecified`), list endpoint section | docs-verified (example only, no field table), fixture-tested |
| `AvailableUpdates[]` = `UpdateId, RevisionNumber, Title, Description, KbArticle, Severity, CvssScore, CveCodes, Category, ReleaseDate`, described as "List of available OS updates" | docs-verified (example), fixture-tested |
| `InstalledUpdates[]` = `UpdateId, RevisionNumber, Title, Description, Severity, ReleaseDate, InstalledAt, InstalledByAgent`, **only** on `GET /api/v3/assets/:id` with `include=InstalledUpdates` | docs-verified (example), fixture-tested. The documented example is reproduced in `tests/fixtures/vsa_x/asset_detail_installed_updates_doc_example.json` |
| `InstalledAt` example `2024-01-07T00:00:00` has **no timezone** | stored verbatim and never converted. Shown as "as reported, timezone unspecified" |
| A per-device update **scan timestamp** | **not documented.** "Scan freshness" is shown as portal collection time plus `LastSeenOnline`, with an explicit note |
| `AvailableUpdates` for non-Windows devices | not established. A non-Windows device without the section is classed `not_supported`, never zero |
| Third-party application patch applicability | not claimed. The UI and reports say "OS updates only" |

## Features implemented

| Task | Result | Evidence |
|---|---|---|
| P2-01 OS update collection | ✅ fixture | `test_patching.py` (21 tests): documented examples, malformed sections, every status value, budgeted per-device detail calls (off by default), least-recently-collected rotation, carry-forward with the original timestamp, a detail 404 fails only that device, a detail 401 fails the run and keeps the last good data, an unsafe device ID never reaches the URL, DB customer-consistency triggers. **Bug found and fixed:** rotation starved never-collected devices because PostgreSQL sorts NULL last in ascending order |
| P2-02 Patch views | ✅ | Summary with explicit denominators: devices "reporting zero" counts only those that returned an empty list, and devices with no update data are shown separately as not collected or non-Windows. Per-KB device counts, device status lists, asset OS-update tab, RPT-04 |
| P2-03 Report schema and permissions | ✅ | Code-defined templates (`/report-templates/`), allowlisted typed filters, `asset` filters checked against the customer (cross-tenant filters return 400), saved views (owner-controlled, optional sharing within the customer), report definitions |
| P2-04 XLSX/PDF | ✅ | One provenance block and one row set feed all three formats (same row count asserted). XLSX cells are string-typed (never formulas), formula prefixes are neutralised and illegal characters stripped. PDF text is XML-escaped (vendor `<font>` markup appears literally), with a branded header/footer and a 5000-row cap (fails safely). Files go to private storage and downloads stream after re-authorisation |
| P2-05 Scheduling | ✅ | Celery Beat dispatcher. IANA timezones with DST behaviour tested (Asia/Nicosia). `(schedule, slot)` is DB-unique, so duplicate dispatches are suppressed. Owner and recipients are re-authorised at every run: a revoked owner means the slot is skipped, and revoked recipients are dropped and audited. Inbox shows only runs still authorised. Read-only sync schedules (revoked mapping means skipped and audited). Hourly purge of expired artifacts (file deleted, row kept, audited) |
| P2-06 Historical snapshots | ✅ | Superseded generations are retained. Regeneration re-pins to the original generation/evaluation IDs: rows are identical after a newer generation is published, and forged pins cannot cross customers. Trend endpoint: one point per day per source from retained generations, each with its denominators and catalog revision identity, no interpolation. The chart palette was validated with the dataviz validator (slot 3 below 3:1 contrast, so direct labels and a table view are provided) |
| P2-07 Reporting gate | ⏳ Open | See the status line above |

## Commands and results (actual output)

```text
backend$ uv run ruff check . && uv run ruff format --check .   → All checks passed! / 119 files already formatted
backend$ manage.py check / makemigrations --check               → no issues / No changes detected
backend$ uv run python -m pytest -q                             → 324 passed in 119.30s
backend$ manage.py spectacular --validate --fail-on-warn        → clean; committed openapi.yaml current
backend$ uv export ... --no-header | diff requirements.lock      → current
backend$ DJANGO_ENV=production ... manage.py check --deploy     → System check identified no issues (1 silenced).
backend$ uvx pip-audit --strict -r requirements.lock            → No known vulnerabilities found (openpyxl, reportlab, tzdata added)
frontend$ npm run lint && npm run typecheck                     → clean
frontend$ npx vitest --run                                      → Tests 34 passed
frontend$ npm run build                                         → ✓ built (448.89 kB / 132.32 kB gzip)
frontend$ npm audit --omit=dev --audit-level=high               → found 0 vulnerabilities
```

Playwright ran against a fresh `portal_e2e` database (migrate, `seed_demo`, runserver with eager Celery and `LOGIN_THROTTLE_RATE=200/min` for the test run only, Vite proxy). **All 16 passed (1.4 min)**: the 10 P0/P1 tests plus 6 P2 tests (Windows-update states, XLSX export, PDF export, regeneration, schedule recipient authorisation, dashboard history with table view). The first P2 run had 4 failures. All were caused by test selectors that had not been updated for the new Reports UI, plus one race on the newest history row. They were fixed in the specs and the full suite was rerun from a fresh database. The server log had 0 ERROR entries.

## TESTING.md coverage added in P2

| ID | Covered by |
|---|---|
| OS-01 | `test_states_never_produce_false_zeros`, `test_documented_installed_updates_keeps_timestamp_raw`, `test_installed_updates_budget_rotation_and_carry_forward` |
| OS-02 | `test_states_never_produce_false_zeros` (absent section → not_collected; non-Windows → not_supported; neither counted as zero), frontend `windows updates › never presents devices without update data as zero`, E2E P2-1 |
| REP-01 | `test_all_formats_same_record_count`, `test_asset_inventory_csv_scoped_with_provenance_and_injection_defence` |
| REP-02 | `test_xlsx_is_valid_string_typed_and_matches_row_count` (no formula cells), CSV tests from P0/P1 |
| REP-03 / AUTH-05 | `test_revoked_recipient_is_dropped_and_loses_inbox_access`, `test_owner_revoked_skips_slot`, `test_recipient_inbox_access_revoked_after_delivery` |
| REP-04 | async generation, `REPORT_MAX_ROWS`, `test_pdf_row_limit_fails_safely`, `test_expired_artifacts_are_purged_and_audited` |
| SEC-02 (PDF) | `test_pdf_is_valid_escapes_markup_and_states_provenance` |
| SOFT-05 / history | `test_regenerated_report_reproduces_original_snapshot`, `test_forged_pins_cannot_cross_tenants`, `test_trends_from_retained_generations_with_identity` |

## Known limitations and risks

1. **No live validation** of the update sections. Real field population, severity vocabulary and per-device call cost are unproven (needs the DEC-04/DEC-10 pilot).
2. InstalledUpdates is budgeted (`installed_updates_budget`, default 0 = off). With rotation, a large estate needs several syncs before coverage is complete. Carried-forward data is labelled with its original collection time.
3. **No e-mail delivery** (DEC-09). Schedules deliver to an in-portal inbox only.
4. Report files are built in memory (bounded by `REPORT_MAX_ROWS` = 100k; PDF 5000 rows). Artifact encryption at rest is P5-03. Superseded generations are kept indefinitely until a retention policy is approved (DEC-09).
5. Trends are computed on request from retained generations (a few queries per point, at most 400 points). Performance at scale is unmeasured (P5-06). OS-update ingestion does one lookup per update entry, which still needs optimisation and measurement at scale.
6. Beat is a single process. Duplicate slot execution is prevented by the DB, but missed slots during downtime are coalesced into one run, not replayed.
7. A DST spring-forward local time that does not exist resolves through Python `zoneinfo` fold rules. This is documented, not configurable.

## Next tasks

* Close the P0-09, P1-10 and P2-07 gates: Docker boot, CI run, sign-off, live pilot, and reporting-owner review of layouts and metric definitions.
* P3-01: verify the IT Glue API (`x-api-key`, JSON:API, regional hosts, paging, rate limit) from <https://api.itglue.com/developer> before writing the connector.

## Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Engineering owner | _pending_ | | |
| Security reviewer | _pending_ | | |
| Reporting owner (DEC-08/DEC-09) | _pending_ | | |
