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
