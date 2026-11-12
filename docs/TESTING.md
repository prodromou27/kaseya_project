# Test strategy, acceptance matrix and release gates

**Important:** This is the **test plan**. No tests have yet been run for the application because code is not included in this docs package. The coding agent must implement and execute tests and publish exact results.

## 1. Test levels

- **Unit:** parsers, version comparators, filters, permission policy helpers.
- **Database/integration:** Django on **real PostgreSQL** in CI, migrations, queries, transactions, snapshots.
- **Connector contract:** recorded synthetic/sanitized vendor JSON, auth/paging/limits/retry/field schema.
- **API:** DRF endpoint permissions, filters, pagination and data correctness.
- **UI:** React component/unit tests; Playwright E2E on running stack.
- **Security:** cross-customer IDOR, SSRF, exports, injection, role escalation, credential leak checks.
- **Resilience:** worker restart during pagination, lost DB connection, 429, last-good snapshot rollback, disaster restore.
- **Pilot/live:** authorized VSA/IT Glue/PSA sandbox or approved single-customer verification with source UI comparisons.

## 2. Mandatory test cases

| ID | Scenario | Expected result |
|---|---|---|
| AUTH-01 | Anonymous API and export requests | 401 / redirect according to auth, no data |
| AUTH-02 | Engineer for Customer A uses Customer B ID in route/query | 403/404, no count or metadata leak |
| AUTH-03 | Engineer retrieves old export of Customer B | Denied even with valid file ID |
| AUTH-04 | Queue job created for wrong customer/source mapping | Rejected before vendor call |
| AUTH-05 | Revoked membership accesses saved view/scheduled report | Denied, pending distribution blocked |
| VSA-01 | `$top=100/$skip` pagination and `TotalCount` handling | All unique assets collected; idempotent |
| VSA-02 | Device missing `InstalledSoftware` or `AvailableUpdates` | Explicit missing/not-collected; no false compliance |
| VSA-03 | HTTP 429 with `Retry-After` | Backoff; no unbounded retries |
| VSA-04 | 401 and invalid TLS chain | Fail closed; no secrets in logs |
| VSA-05 | Organization external ID unmapped | Quarantine, never default customer |
| SYNC-01 | Worker killed halfway through full sync | Old complete published generation survives |
| SYNC-02 | Retry same idempotency key | No duplicate observations/published generations |
| SYNC-03 | Source deletion while paginating | No premature deletion on incomplete crawl |
| SOFT-01 | Windows 4-part versions | Correct numeric comparison |
| SOFT-02 | Chrome stable vs ESR/beta and x86 vs x64 | No cross-channel false comparisons |
| SOFT-03 | Missing version/alias/catalog | Unknown or unsupported as appropriate |
| SOFT-04 | Approved exclusions | Excluded with approver and expiry; raw observation unchanged |
| SOFT-05 | New catalog revision | Historical reports remain reproducible |
| OS-01 | Available vs installed KB | Correct source states and counts |
| OS-02 | Device unscanned or API section absent | Unavailable/unknown, not zero |
| ITG-01 | JSON:API `data/attributes/relationships` paging | Correct normalization and scope |
| ITG-02 | Attempt to call password endpoint | Denied by adapter allowlist |
| PSA-01 | Zone discovery and wrong API zone | Correct zone selection; safe failure |
| PSA-02 | Query >500 records | All pages/traversal handled without duplication |
| PSA-03 | API user with limited fields | Missing fields handled, no authorization bypass |
| REP-01 | UI list vs CSV/XLSX/PDF for same filters | Identical authorized record set |
| REP-02 | Cell begins `=`, `+`, `-`, `@`, tab or CR | Formula injection neutralized |
| REP-03 | Report generation after membership revocation | Delivery/download prohibited |
| REP-04 | Large export | Async, resource limits, correct cutoff and expiry |
| SEC-01 | User-supplied connector URL points to metadata service | SSRF blocked |
| SEC-02 | Malicious HTML in vendor-supplied text | Safely escaped in UI/PDF |
| SEC-03 | Secrets injected into vendor errors | Redacted in logs and UI |
| DR-01 | Backup and isolated restore | App starts, DB/catalog/audit/report recovered; evidence recorded |

## 3. Example commands after implementation

The coding agent must supply correct commands in `pyproject.toml`, `package.json`, Compose and CI. Suggested targets:

```bash
# Backend on PostgreSQL test service
cd backend
ruff check .
python manage.py check --deploy
pytest -q

# Frontend
cd ../frontend
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build

# End-to-end (with a running fixture-backed stack)
npx playwright test
```

`manage.py check --deploy` flags production hardening settings and should be run against production-like configuration; its output must be reviewed rather than blindly treated as a complete security audit.

## 4. CI expectations

On every pull request: formatter/linter/type check, backend PostgreSQL tests, frontend tests/build, migrations, secret scan, dependency scan and generated OpenAPI schema consistency check. Nightly or pre-release: Playwright E2E, load/large export and restore tests when infrastructure available.

CI must fail if customer-isolation checks, migration tests or vendor read-only allowlist tests fail. Never claim CI success until actual workflow completed.

## 5. Pilot acceptance

- One explicitly approved nonrestricted customer with read-only VSA token.
- Documented inventory count comparison with VSA UI and sample installed software version comparisons.
- Count discrepancies and explain (API missing fields, timing, mapping, unsupported devices).
- Confirm query budget, sync duration, 429 behavior, stale warnings and worker recovery.
- Generate customer CSV/XLSX/PDF and verify record totals and source provenance.
- Independent security review validates tenancy and credentials handling.

## 6. Release gate

**Release candidate:** tests green, zero known severe tenant leaks, no plaintext credentials, live pilot source comparisons, SSO + MFA, off-host encrypted backup + isolated restore, trained admin, report retention and data-processing approval. **Production-ready** claim requires explicit sign-off, not merely green unit tests.
