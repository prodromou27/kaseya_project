# Expected Excel/CSV inventory to VSA onboarding reconciliation

## Workflow

Customer → upload `.xlsx` or `.csv` → inspect sheets/headers → map fields → preview/validate → choose most recent **complete** approved VSA generation → async compare → review uncertain matches → export multi-sheet XLSX → save immutable run.

### Allowed input columns

Hostname, FQDN, SerialNumber, MAC, AssetTag, IPAddress, SourceDeviceId (when known), ExpectedOrganization, ExpectedSite, ExpectedGroup, DeviceType, Department, Notes. Provide column mapper and reusable template per customer. Never assume a single standardized spreadsheet layout. Support multiple worksheets, Unicode and case variations.

### Security

- Hard size/row limits, MIME and magic-byte checks, no `.xlsm` or executable formats; reject zip bombs and external links.
- Do not evaluate spreadsheet formulas or resolve external references. Strip/escape leading `=`, `+`, `-`, `@` when exporting CSV/Excel text fields.
- Store uploads private/encrypted with TTL, tenant scope and delete/retention controls. Limit previews, audits and logs; never render untrusted cell contents as HTML.
- Only compare with VSA data mapped to exactly the authorized customer and selected instance.

## Matching algorithm

Match within same **approved customer + VSA instance**. Normalize strings while retaining original values. Precedence (when unique within authorized scope):
1. Verified source device identifier.
2. Serial number (unique and non-placeholder).
3. Trusted asset tag (unique and reviewed).
4. Exact FQDN (unique, matching known domain scope).
5. Hostname (unique only within validated site/org scope).
6. MAC is corroboration; use cautiously for virtual and cloned interfaces.
7. IP address is weak evidence only, **never sole auto-confirming identifier**.

Never fuzzy-auto-merge; flag ambiguous candidates for manual review. Preserve evidence used, candidate count, reason and reviewer. A row with blank/malformed identifiers is `INVALID` not simply `NOT_FOUND`. Duplicate import rows are explicit.

## Primary row classification

- `MATCHED_CORRECT` — correct org/site/group.
- `MATCHED_WRONG_GROUP` — verified device found, group mismatch.
- `MATCHED_WRONG_SITE` — site mismatch.
- `REVIEW_WRONG_ORGANIZATION` — scope mismatch requires authorized review; do not leak other customers.
- `NOT_FOUND_IN_COMPLETE_SNAPSHOT` — no match in valid inventory (not definitive proof agent never installed).
- `AMBIGUOUS` — multiple plausible matches.
- `DUPLICATE_INPUT` — duplicate spreadsheet entry.
- `INVALID_INPUT` — missing/invalid identifiers.

Secondary flags: `OFFLINE`, `STALE_AGENT`, `OLD_AGENT`, `NO_PATCH_POLICY`, `STALE_SOURCE`, `MISSING_NETWORK_DATA`. An offline device already matched remains onboarded. `UNEXPECTED_VSA_ASSET` is calculated as a separate inverse-set result for VSA entries not represented by accepted expected rows.

## Report workbook tabs

`Summary`, `All Expected`, `Matched Correct`, `Wrong Group`, `Wrong Site`, `Not Found`, `Ambiguous`, `Duplicate/Invalid`, `Unexpected VSA`, `Recommendations`. Each row includes evidence, matched source ID, expected/actual hierarchy, source generation/time and reviewer state.

## Historical comparisons

Store immutable upload hash, mapping config version, comparison logic version, VSA generation ID, results and operator decisions. Show progress across periods only when matching definitions and denominator scope are comparable. Re-run against new snapshot without changing historical results.

## Acceptance scenarios

- 100-row test classifies 80 exact, 10 not found, 5 wrong group, 3 ambiguous and 2 duplicates; totals consistent.
- Same hostname in separate customers cannot cross-match; no source identifiers leak.
- VSA generation incomplete => comparison blocked with explanation.
- Same device has two network interfaces => matching handles both without duplicate device count.
- “not found” never states “agent not installed” as a proven fact.
- XLSX export and CSV injection tests pass.

## Implementation notes (`dcecf60`, 2026-11-13; fixture-tested only)

Code: `backend/apps/onboarding/` (`importer.py`, `matching.py`, `services.py`, `workbook.py`). UI: **Onboarding check**.

| Topic | As implemented |
|---|---|
| Permissions | View runs/results: `customer.read`. Upload, preview, compare, review: `customer.sync` (engineer/admin). Workbook/CSV: `customer.export`. |
| Limits | 5 MB (`ONBOARDING_MAX_UPLOAD_BYTES`), 20,000 rows (`ONBOARDING_MAX_ROWS`), 64 columns, 20 visible sheets, 512 chars/cell. The XLSX container is checked before parsing: 2,000 parts, 64 MB expanded, ratio 200:1 for parts > 1 MB. |
| Refused content | Any extension except `.xlsx`/`.csv`; mismatched magic bytes; VBA/macro content types, `xl/externalLinks/`, `xl/activeX/`, `xl/embeddings/`, `xl/macrosheets/`; `<!DOCTYPE`/`<!ENTITY` in any XML part. openpyxl parses with defusedxml and `keep_links=False`. |
| Formulas | Never evaluated. Cached results are not trusted: a formula cell reads as empty and is counted (`formula_cells_ignored`). Exports prefix `= + - @` with `'` and write string-typed cells. |
| Storage | Private volume `ONBOARDING_STORAGE_DIR` with an opaque key, sha256 verified on every read, purged after `ONBOARDING_UPLOAD_TTL_HOURS` (72 h) or on delete. App-level encryption is not implemented (same as report artifacts, pending DEC-07 vault). Results (including input values) are kept as immutable history. |
| Snapshot gate | Only the customer's current published generation from an approved mapping is accepted, and its site/group crawl must be `collected`. Snapshots older than `DATA_STALE_AFTER_HOURS` need an explicit acknowledgement, and every row is then flagged `STALE_SOURCE`. Another customer's generation ID is treated as unknown. Blocked attempts are audited. |
| Identifiers | Asset tags are accepted but VSA X reports no asset-tag field, so they never match (stated in evidence). An asset-tag-only row is `INVALID_INPUT`. FQDN = VSA `Name` + reported domain. A hostname with dots is also tried as an FQDN. |
| MAC / IP | A MAC-only hit goes to review (`AMBIGUOUS`). Locally administered MACs are ignored. An IP is weak evidence: an IP-only row with a hit goes to review, and an IP never rescues a row whose strong identifiers found nothing. |
| Duplicates | Same identity (ID, then serial, then FQDN, then hostname + expected site) as an earlier row, **or** resolution to an already-matched device. |
| Secondary flags | `OFFLINE` (> 24 h before snapshot), `STALE_AGENT` (> 7 days or never seen), `STALE_SOURCE`, `MISSING_NETWORK_DATA`. `NO_PATCH_POLICY` (since `ff7a956`, logic `onboarding-match-2`) marks only VSA's explicitly configured No Policy; an unknown or unreported assignment is never flagged. `OLD_AGENT` (no approved baseline) is listed as *not evaluated*, never silently empty. |
| Unexpected set | Devices not matched by any accepted row. Candidates of unresolved ambiguous rows are counted separately (`unexpected_pending_review`). |
| Review | A one-time decision on `AMBIGUOUS` (choose a listed candidate or no match) or `REVIEW_WRONG_ORGANIZATION` (confirm or no match). The engine's classification and evidence are immutable (DB trigger). The decision is stored in `reviewed_*` and audited. |
| Workbook | Excel forbids `/` in sheet names, so the spec's `Duplicate/Invalid` tab is named **`Duplicate-Invalid`**. `REVIEW_WRONG_ORGANIZATION` rows appear on the **Wrong Site** tab (and on All Expected). Exports are generated on demand from stored results and audited; no file is retained. |
| Moves | Never performed. Recommendations point to the approved VSA X change process (VSA5 remains BLOCKED_APPROVAL). |
| Not validated | Real customer spreadsheets and live VSA naming/serial quality are **LIVE_VALIDATION_PENDING**. The nginx upload location and compose volume were never booted. |
