# Phase 1 acceptance and security test matrix (VSA only)

## Acceptance evidence

Record exact command, timestamp, test run link or terminal output, environment, customer-sanitized dataset and commit in `IMPLEMENTATION_EVIDENCE.md`. Fixture tests are not live integration validation. Use PostgreSQL for all database/concurrency tests and a real browser for E2E.

| ID | Test | Expected result |
|---|---|---|
| AUTH-01 | Anonymous list/detail/export/file access | denied |
| AUTH-02 | Customer A user guesses B's device, group, job or report ID | denied without metadata leak |
| AUTH-03 | Customer A engineer selects global aggregation | denied without global role |
| CON-01 | VSA token bad/expired/403/429/5xx | correct stop/retry class, no secrets logged |
| CON-02 | 200 pages, incremental where documented, restart mid-sync | idempotent and last complete generation retained |
| CON-03 | Source org unmapped | quarantined, no record bound to guessed customer |
| INV-01 | Same hostname and IP in two instances | two separate devices, never merged |
| INV-02 | Asset has two NICs and multiple IPs | all preserved; no duplicate device row |
| INV-03 | Device is offline but in VSA | onboarded with OFFLINE secondary flag |
| SW-01 | Chrome 120 vs reviewed compatible 125 | `OUTDATED`, no pending patch claim |
| SW-02 | ESR vs stable and unparsable version | unknown or compatible catalog; never forced wrong comparator |
| SW-03 | Catalog revised after prior report | historical report references old revision and stays reproducible |
| OS-01 | No policy, stale scan, no available updates | three distinct states; no false `fully patched` |
| OS-02 | AvailableUpdates and InstalledUpdates | OS labels only, severity/KB only if exposed |
| PATCH-01 | Pending 3rd-party status not available | explicit `UNVERIFIED`, no fabricated data |
| XL-01 | 100 rows: 80 matched, 10 missing, 5 wrong group, 3 ambiguous, 2 duplicates | totals correct with reasons |
| XL-02 | Duplicate hostname across customers | never cross-matched, no other customer exposed |
| XL-03 | Invalid file, macros, links, formula injection, massive upload | rejected/sanitized safely |
| XL-04 | Reconciliation using incomplete VSA generation | blocked; previous result unchanged |
| NET-01 | IPv4+IPv6, masks, virtual and multi-interface | correct derived network or unknown |
| NET-02 | IP reused across sites / changes over time | review finding, no false certainty |
| OPS-01 | Security observation unknown/stale | not counted as secure or insecure |
| HIST-01 | Incomplete sync makes record disappear | not classified deleted |
| REP-01 | Authorized XLSX/PDF/CSV with filters and as-of | correct counts, provenance and private access |
| REP-02 | Cross-customer scheduled report recipient | rejected |
| MOVE-01 | Viewer/proposer self-approves or cross-customer target | denied, no vendor write |
| MOVE-02 | Source group changed since approval | invalidated, no vendor write |
| MOVE-03 | Timeout after VSA applied move | re-read; no repeated PUT; unknown if uncertain |
| MOVE-04 | Move disabled on customer | no write route execution or token access |
| LOAD-01 | 100k devices and millions of observations | pagination, no in-memory all-row aggregation |
| DR-01 | Restore from encrypted off-host backup into isolated environment | app/data/report integrity validated |

## End-to-end engineer journey

Login → select authorized customer → browse group → search device → software and OS updates tabs → import expected Excel → run comparison → view wrong groups/network → export XLSX → inspect saved historical comparison. Verify user cannot pivot to another customer by editing route/query/asset ID. Optional move journey runs in separate feature-gated pilot only.

## Go/no-go

Required: all VSA0–VSA3 P0 tests, regression, permission/IDOR, successful migrations, restore test and live VSA pilot acceptance. VSA5 is a separate go/no-go and may remain disabled. Any unsupported API capability must be visibly labeled, not treated as a reason to fake success.
