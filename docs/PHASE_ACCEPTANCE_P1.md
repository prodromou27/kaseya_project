# Phase P1 acceptance record: VSA X inventory and software versions

**Status:** P1-01 to P1-09 are implemented and tested against **fixtures only**. **P1-10 (the MVP gate) is open.** It depends on the P0 gate (Docker boot, CI) and on owner sign-off. A live pilot is optional and needs an approved read-only token (DEC-04, DEC-10).

| Field | Value |
|---|---|
| Git revision | `23550d1` on `main` (local repository; no remote, no CI run) |
| Date | 2026-11-12 |
| Environment | Windows 11, Python 3.12.10, Node 24.22, PostgreSQL 16.2 (local disposable cluster). No Docker, no Redis (Celery in eager mode). |
| Data basis | Synthetic test data and the fictional `seed_demo` fixture tenant. **No live VSA X calls were made. No credentials were used.** |

## Vendor API verification (VSA X)

The public reference at <https://api.vsax.net/> was retrieved on 2026-11-12. The adapter relies only on the facts below, which are recorded in `backend/apps/integrations/vsa/capabilities.json`.

| Fact | Status |
|---|---|
| Basic auth `TOKEN_ID:TOKEN_SECRET`, HTTPS only | docs-verified, fixture-tested |
| `GET /api/v3/assets`, `$top` ≤ 100 (default 100), `$skip`, OData `$filter` / `$orderby`, `include` sections | docs-verified, fixture-tested |
| `OrganizationId`, `SiteId` and `ComputerId` are integers and filterable; `Identifier` is a string | docs-verified, fixture-tested |
| Envelope `{Data, Meta{TotalCount, ResponseCode}}` | docs-verified, fixture-tested (the documented example is reproduced in `tests/fixtures/vsa_x/assets_doc_example.json`) |
| `InstalledSoftware[]` = `Name`, `Publisher`, `Version` only (no architecture, no channel) | docs-verified, so architecture-specific references are classified `unknown` |
| `GET /api/v3/organizations` (`Id` int, `Name`, `Type`) | docs-verified, fixture-tested |
| 429 with `Retry-After` (seconds); 3600 req/h per token+endpoint; failed requests limited per IP (100/min) | docs-verified; client never retries 401/403 |
| Error body shape | **not documented**, so the adapter uses status codes only and never stores bodies |
| Third-party per-device missing-patch applicability | **not established**, so not claimed. All UI and report text says "version comparison only" |
| Live behaviour (real paging, real counts, real field population) | **not tested** (no approved token) |

## Features implemented (task IDs)

| Task | Result | Evidence |
|---|---|---|
| P1-01 Documented VSA adapter | ✅ fixture | `test_vsa_adapter.py` (50 tests): documented example normalisation, sensitive `AssetInfo` fields dropped (Product Key, Registered/Last Logged On user, Owner Name), malformed records and pages, pagination at 0/1/99/100/101/250, OData-injection-proof integer org IDs, 429/Retry-After (honoured and bounded), 5xx and timeout backoff, 401/403 not retried, redirects and non-JSON responses fail closed, GET-only client with path allowlist, DNS egress checks, `env:` credential references |
| P1-02 Safe sync engine | ✅ fixture | `test_sync.py` (26 tests): interrupted sync keeps the last good generation and resumes from its checkpoint; replay and idempotency key; one active run per scope (DB constraint); source changes during the crawl are detected and not published; auth failure keeps published data; drop guard; bounded attempts |
| P1-03 Organisation mapping and quarantine | ✅ | Each collection is filtered to one approved org. Records from other orgs, malformed records and vendor-ID customer conflicts are quarantined, never attributed. Revoking a mapping hides its data. DB triggers reject customer-mismatched rows |
| P1-04 Assets UI | ✅ | Server-side search, filters, ordering and pagination; facets; detail with history; freshness (fresh, stale, never synced); fixture labelling; "not collected" state; E2E |
| P1-05 Installed software | ✅ | Raw name, publisher and version preserved per generation, including duplicate entries; counts reconcile (`row_count`, `software_row_count`, API and CSV) |
| P1-06 Software catalog | ✅ | Products (channel, edition and architecture are part of identity), aliases (proposal then review), import preview (dry run, flags version decreases), **separate-reviewer approval**, immutable revisions (model guard and PostgreSQL trigger) |
| P1-07 Comparator | ✅ | `test_comparator.py` (32 tests): 4-part numeric comparison, stable/beta/ESR channels kept apart, architecture, missing, pre-release and unparseable versions, ambiguous alias or revision, future-effective revisions, exceptions |
| P1-08 Compliance UI | ✅ | Summary with explicit numerators and denominators (REPORTING.md §2); unknown, unsupported, excluded and newer shown separately; per-product version distribution; drill-down with catalog evidence; exceptions; metric reconciliation test |
| P1-09 Scoped CSV | ✅ | RPT-01 and RPT-03 with a pinned snapshot, the REPORTING §3 provenance block, the limitations statement and formula-injection defence (vendor hostname `=HYPERLINK(...)` is neutralised). The export record set equals the API record set (REP-01) |
| P1-10 MVP gate | ⏳ Open | Demo data, fixture completeness and the read-only allowlist are done. Still needs the P0 gate (Docker, CI), sign-off and, optionally, an approved live pilot |

## Commands and results (actual output)

```text
backend$ uv run ruff check . && uv run ruff format --check .
All checks passed! / 107 files already formatted
backend$ uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run
System check identified no issues (0 silenced). / No changes detected
backend$ uv run python -m pytest -q
276 passed in 31.40s
backend$ manage.py spectacular --validate --fail-on-warn   → no warnings; committed openapi.yaml current
backend$ DJANGO_ENV=production ... manage.py check --deploy --fail-level WARNING
System check identified no issues (1 silenced).
backend$ uvx pip-audit --strict -r requirements.lock      → No known vulnerabilities found
frontend$ npm run lint && npm run typecheck                 → clean
frontend$ npx vitest --run                                  → Test Files 4 passed, Tests 30 passed
frontend$ npm run build                                     → ✓ built (418.88 kB JS / 125.10 kB gzip)
frontend$ npm audit --omit=dev --audit-level=high           → found 0 vulnerabilities
```

Playwright ran against a running fixture stack: a fresh `portal_e2e` database, then `migrate` and `seed_demo`, then `runserver` with eager Celery and `LOGIN_THROTTLE_RATE=200/min` (raised for the test run only, because the 10/min production default correctly throttled the 10th E2E login), plus the Vite proxy:

```text
  ok  1 anonymous user is sent to login
  ok  2 engineer sees only their customer and cannot reach another by URL or API
  ok  3 engineer cannot open Customer B using its real ID (IDOR)
  ok  4 super admin approves the demo source mapping and the audit trail records it
  ok  5 customer admin generates and downloads a scoped audit report
  ok  6 engineer syncs the approved fixture source and browses inventory
  ok  7 software versions show separate populations and the non-patch disclaimer
  ok  8 engineer exports a scoped inventory CSV with provenance
  ok  9 viewer of DEMO-B cannot reach DEMO-A inventory and cannot sync
  ok 10 catalog import cannot be approved by its own submitter
  10 passed (32.8s)
```

The server log had 0 ERROR entries.

## TESTING.md coverage added in P1

| ID | Covered by |
|---|---|
| VSA-01 | `test_pagination_collects_all_unique_assets`, `test_full_sync_publishes_and_counts_reconcile` |
| VSA-02 | `test_missing_software_section_is_not_collected_not_empty`, `test_missing_software_section_recorded_as_not_collected`, E2E 6 |
| VSA-03 | `test_429_honours_retry_after_then_succeeds`, `test_429_retries_are_bounded`, `test_rate_limit_exhaustion_pauses_run` |
| VSA-04 | `test_auth_failure_stops_immediately_without_retry`, `test_auth_failure_preserves_published_data`. TLS: `verify=True` is hard-coded and there is no parameter to disable it. **A live invalid-chain test is not possible offline** |
| VSA-05 | `test_records_from_other_organisations_are_quarantined_never_attributed`, `test_unapproved_mapping_cannot_be_synced` |
| SYNC-01/02/03 | `test_interrupted_sync_keeps_last_good_generation_then_resumes`, `test_replay_of_completed_run_is_noop`, `test_idempotency_key_returns_same_run`, `test_source_changing_during_crawl_is_not_published` |
| SOFT-01..04 | `test_comparator.py`, `test_exceptions_scoped_and_raw_observation_unchanged` |
| SOFT-05 | `test_new_revision_keeps_history_reproducible` |
| AUTH-04 (sync) | `test_mapping_revoked_after_request_is_refused_in_worker`, `test_requester_losing_sync_capability_is_refused_in_worker` (no vendor call is made) |
| REP-01/02 | `test_asset_inventory_csv_scoped_with_provenance_and_injection_defence`, `test_software_csv_matches_api_and_states_limitations` |
| SEC-01 (runtime) | `test_live_instance_rechecks_allowlist_on_every_request`, `test_dns_resolution_to_internal_addresses_is_blocked` |

## Known limitations and risks

1. **No live VSA X validation.** Field population, real `TotalCount` behaviour, actual rate-limit headers and performance at scale are unproven. A pilot needs an approved read-only token (DEC-04) and an approved pilot customer (DEC-10).
2. **`$skip` paging residual risk.** The engine rejects crawls in which `TotalCount` changes or unique records do not reconcile. If records are added and removed in **equal numbers** between pages, the change is not detectable from the documented API; a later full re-sync corrects it.
3. **DNS rebinding.** Destinations are checked at resolution time, but a time-of-check/time-of-use gap remains. Production must also enforce an egress firewall allowlist (P5-02).
4. Credentials resolve only from `env:NAME` / `NAME_FILE` references. A vault backend is P5-02 (DEC-07).
5. No scheduled syncs yet (Celery Beat is P2-05). Syncs are started by hand by users with `customer.sync`.
6. Catalog alias matching supports only `exact` and `prefix` (no regex, which avoids ReDoS and over-broad matches). The demo catalog is **illustrative**: its evidence URL is `*.invalid` and its versions are not verified vendor facts.
7. The compliance re-evaluation after catalog changes runs as a Celery task over all current generations. Its performance at scale is unmeasured (P5-06).
8. Assets have no `asset_identifiers` or network-interface tables yet. They are deferred until needed for P3 matching.

## Next tasks

* Close the P0-09 and P1-10 gates: Docker boot, CI run, sign-off; optional live pilot.
* P2-01: re-verify the `Updates`, `AvailableUpdates` and `InstalledUpdates` documentation, then extend `include` and the per-device detail budget.

## Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Engineering owner | _pending_ | | |
| Security reviewer | _pending_ | | |
| Reporting owner (catalog/metrics, DEC-08) | _pending_ | | |
