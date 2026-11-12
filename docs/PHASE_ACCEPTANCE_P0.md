# Phase P0 acceptance record — Application foundation

**Status:** P0-01 and P0-03 to P0-08 implemented and tested. **P0-02 (Docker stack) is implemented but has not been booted**, because Docker is not available in the development environment. **P0-09 (foundation gate) is open** until the Docker boot is shown and an owner signs off.

| Field | Value |
|---|---|
| Git revision / branch | `d799241` on `main` (local repository; no remote, so no CI run yet) |
| Date | 2026-11-12 |
| Environment | Windows 11 workstation, Python 3.12.10, Node 24.22, PostgreSQL **16.2** (local disposable cluster on 127.0.0.1:55432). No Docker and no Redis. |
| Data basis | Synthetic test factories and `seed_demo` DEMO data only. **No vendor data, no vendor credentials, no live API calls.** |

## Features implemented (task IDs)

| Task | Result | Evidence |
|---|---|---|
| P0-01 Repository and quality setup | ✅ | uv-locked backend (`uv.lock`, hash-pinned `requirements.lock`), npm lock file, Ruff (lint + format), ESLint (strict TS + jsx-a11y), TypeScript `strict`, pytest, Vitest, Playwright, CI and security workflows. **A clean clone ran every check successfully** (see below). |
| P0-02 Docker developer stack | ⚠️ Implemented, **not booted** | `compose.dev.yml` and `compose.prod.yml` (PostgreSQL and Redis only on an `internal: true` network; only the proxy publishes a port, bound to 127.0.0.1 in dev), non-root images, health checks, Docker secrets in prod. The Compose files were parsed with PyYAML. The `compose` CI job will run `docker compose config`, build both images and check for non-root users. |
| P0-03 Core database and migrations | ✅ | Models User, Role, Customer, CustomerMembership, IntegrationInstance, CustomerSourceMapping, AuditEvent, plus ReportRun and ReportArtifact. `test_migrations.py` migrates every project app **down to zero and back up on PostgreSQL 16.2**, and confirms the audit trigger is dropped and recreated. |
| P0-04 Identity and sessions | ✅ (mock IdP) | One-time `bootstrap_admin`; local login with CSRF and throttling; server-side DB sessions with HttpOnly and SameSite cookies, idle and absolute timeouts. OIDC uses the authorization-code flow with PKCE, and its state, nonce, signature, issuer, audience, expiry and `amr` checks are tested against a mock IdP with real RS256 keys. **Not tested against a real Entra tenant** (that is P5-01). |
| P0-05 Tenant authorization | ✅ | One policy module (`apps/accounts/scope.py`). IDOR tests cover list, search, detail, nested routes, report detail, artifact download, jobs (AUTH-04) and revocation (AUTH-05). A mutation check broke the policy on purpose: 5 and then 10 isolation tests failed, which shows the tests catch leaks. |
| P0-06 Customer admin UI | ✅ | Customer CRUD (archive, never delete) for super admins only; delegated grants (customer admins may grant only engineer or viewer, and cannot edit their own or other admins' memberships); mapping proposal by customer admins, then approve, reject or revoke by a super admin. Role matrix tests; E2E mapping approval. |
| P0-07 Audit and errors | ✅ | Append-only audit enforced in the model, the queryset **and a PostgreSQL trigger** (raw SQL UPDATE and DELETE are rejected). JSON logs with redaction of message, args, extras and exceptions. Request IDs. Standard `{"error":{code,message,details,request_id}}` envelope; 500s are sanitised. |
| P0-08 UI foundation | ✅ | Navigation, customer selector (server-authorised list; forged stored IDs are ignored), account status, empty, loading and error states, accessible TanStack table shell, ARIA tabs with keyboard support, and honest "not implemented" pages for P1–P4 modules. |
| P0-09 Foundation gate | ⏳ Open | Requires: (1) a Docker Compose boot on a Docker host, (2) a first green CI run, (3) owner sign-off. |

## Commands and results (actual output)

Backend (`backend/`, `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432`):

```text
$ uv run ruff check . && uv run ruff format --check .
All checks passed!
77 files already formatted
$ uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run
System check identified no issues (0 silenced).
No changes detected
$ uv run python -m pytest -q
146 passed in 10.94s
$ DJANGO_ENV=production ... uv run python manage.py check --deploy --fail-level WARNING
System check identified no issues (1 silenced).      # security.W021 (HSTS preload) — see ADR-013
$ uv run python manage.py spectacular --file openapi.yaml --validate --fail-on-warn
(no warnings; committed openapi.yaml is current)
$ uvx pip-audit --strict -r backend/requirements.lock
No known vulnerabilities found                        # after upgrading DRF 3.16.1 → 3.18.3 (3 CVEs)
```

Frontend (`frontend/`):

```text
$ npm run lint && npm run typecheck          # clean
$ npx vitest --run
Test Files  3 passed (3)
     Tests  23 passed (23)
$ npm run build
dist/assets/index-*.js  387.93 kB │ gzip: 117.90 kB   ✓ built
$ npm audit --omit=dev --audit-level=high
found 0 vulnerabilities
```

Clean clone (`git clone` → `uv sync --frozen` → `npm ci` → all checks): **146 backend tests passed, 23 frontend tests passed, lint, typecheck and build all green.**

Proof of boot (without containers): fresh `portal_e2e` database → `migrate` → `seed_demo` (run twice to confirm it is idempotent) → `manage.py runserver` with eager Celery → Vite dev server proxying `/api` → `GET /api/v1/health/ready/` returned `{"status":"ok","checks":{"database":"ok"}}` →

```text
$ DEMO_USER_PASSWORD=*** npx playwright test
  ok 1 anonymous user is sent to login
  ok 2 engineer sees only their customer and cannot reach another by URL or API
  ok 3 engineer cannot open Customer B using its real ID (IDOR)
  ok 4 super admin approves the demo source mapping and the audit trail records it
  ok 5 customer admin generates and downloads a scoped audit report
  5 passed (38.5s)
```

The server log for the run had no ERROR entries and no 5xx responses. The only 401 and 404 entries came from the negative tests.

## Security and tenant test mapping (TESTING.md)

| ID | Covered by |
|---|---|
| AUTH-01 | `test_auth.py::test_every_non_public_api_route_rejects_anonymous_requests` (route sweep over every API pattern and method) |
| AUTH-02 | `test_tenant_isolation.py::test_cross_customer_routes_return_404_without_metadata`, `..._indistinguishable`, `test_search_cannot_reveal_other_customer`; E2E test 3 |
| AUTH-03 | `test_report_artifact_of_other_customer_denied_even_with_valid_id` |
| AUTH-04 | `test_job_for_wrong_customer_is_rejected_in_worker` |
| AUTH-05 | `test_revoked_membership_loses_access_immediately`, `test_report_download_requires_fresh_authorization`, `test_pending_job_blocked_after_revocation` |
| REP-02 | `test_reports.py::test_neutralize_cell`, `test_audit_csv_report_end_to_end` |
| REP-03 | `test_report_download_requires_fresh_authorization` |
| SEC-01 | `test_admin_api.py::test_connector_url_policy_blocks_ssrf` (13 cases: metadata IP, loopback, userinfo, non-https, path, port, unapproved private IP and others) |
| SEC-02 | `components.test.tsx` (vendor-style HTML is rendered as text); React escapes by default and the code never uses `dangerouslySetInnerHTML` |
| SEC-03 | `test_audit_and_errors.py::test_redact_text_scrubs_secret_values`, `test_logs_redact_message_args_extras_and_exceptions` |

## Vendor API status

| Provider | Docs-verified | Fixture-tested | Live-tested |
|---|---|---|---|
| Kaseya VSA X | Not yet re-verified; no adapter code in P0 | No | No |
| IT Glue | Regional hostnames used only as the egress allowlist default | No | No |
| Autotask PSA | No default host assumed | No | No |

No vendor HTTP client exists in P0. Fixture integration instances must use `https://*.invalid` and cannot hold credential references.

## Known limitations and risks

1. **The Docker stack has never been booted** (P0-02 and the P0-09 gate). The Dockerfiles, Compose files and nginx configs still need to be validated on a Docker host, and then on the AlmaLinux target with SELinux enforcing.
2. **No CI run yet.** The repository is local only. The workflows are written but have not been run.
3. **OIDC is tested only against a mock IdP.** Entra-specific behaviour (claims, `amr` presence, groups) still needs UAT (P5-01, DEC-03).
4. Local test PostgreSQL is a pip-packaged 16.2 build (pgserver) with the tz database added by hand. CI uses the official `postgres:16-alpine` image.
5. Report artifacts are stored unencrypted on a private volume; `encryption_key_ref` exists but is not used yet (P2-04 and P5-03). A retention purge job is not implemented yet (P2).
6. Mapping approval does not enforce four-eyes review: a super admin can propose and approve the same mapping. This is recorded as open decision DEC-11.
7. Sessions are not invalidated server-side when a membership is revoked. That is not needed for isolation, because every request re-checks membership; it is only needed if policy requires forced logout.

## Next phase tasks

* Close P0-09: boot `compose.dev.yml` on a Docker host, run Playwright with `E2E_BASE_URL=http://127.0.0.1:8080`, push to a private remote and get green CI, then owner sign-off.
* P1-01: re-verify the VSA X API at <https://api.vsax.net/> before writing the adapter.

## Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Engineering owner | _pending_ | | |
| Security reviewer | _pending_ | | |
