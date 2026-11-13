# Threat model and security review (VSAP-03)

**Date:** 2026-11-13.
**Scope:** the portal as implemented (Django/DRF API, React SPA, Celery, PostgreSQL, Redis, nginx), the read-only
VSA X connector, and the AlmaLinux/Compose deployment files.
**Method:** STRIDE per trust boundary, automated scanning, and regression tests. This is an engineering review by the
implementer, **not** an independent penetration test. An independent review is still required before production
(section 6).

## 1. Assets and trust boundaries

**Assets:**

* customer inventory and network data;
* expected-inventory uploads;
* audit log;
* vendor credentials (references only);
* user sessions;
* report files;
* backup archives and their encryption key.

**Trust boundaries:**

| # | Boundary | Crossing |
|---|---|---|
| B1 | Browser ↔ nginx proxy | TLS (`proxy` 443), the only published service |
| B2 | Proxy ↔ Django | internal `web` network |
| B3 | Django/Celery ↔ PostgreSQL/Redis | internal-only `data` network (`internal: true`) |
| B4 | Celery worker ↔ VSA X | outbound HTTPS to one allowlisted host, GET only |
| B5 | Uploaded spreadsheet → importer | untrusted file content |
| B6 | Customer A ↔ customer B data | logical tenancy inside one database |
| B7 | Backup host ↔ off-host store | encrypted archives only |

## 2. STRIDE analysis

| Threat | Where | Controls (code / config) | Evidence |
|---|---|---|---|
| **S**poofing a user | B1 | Session cookies `HttpOnly`, `Secure` in production, `SameSite=Lax`; CSRF token on writes; 30-min idle timeout; login throttle (`10/min`); Django password validators; OIDC (Entra) with MFA delegated to the IdP | `test_auth.py`, `test_oidc.py` (mock IdP) |
| Spoofing the vendor | B4 | `verify=True` hard-coded (no switch to disable TLS checks); redirects not followed | `test_vsa_adapter.py` |
| **T**ampering with history | DB | Audit table is append-only (DB trigger); reconciliation results immutable (trigger); catalog revisions immutable; reports regenerate from pinned generations | `test_audit_and_errors.py`, `test_onboarding.py`, `test_restore_check.py` |
| Tampering via uploads | B5 | `.xlsx`/`.csv` only, magic bytes, size/row/column/sheet/cell limits; zip-bomb, macro/VBA, ActiveX, embedding, external-link and DTD rejection **before** parsing; defusedxml; formulas never evaluated | `test_onboarding.py` (importer tests) |
| Spreadsheet formula injection in exports | B1 | Every exported cell is neutralised and written as a string | `test_reports.py`, `test_onboarding.py` |
| **R**epudiation | all | Audit events with actor, customer, target and request ID for logins, denials, syncs, exports, approvals and reviews; two-person approvals record proposer and approver | audit assertions across suites |
| **I**nformation disclosure across customers | B6 | Every customer route resolves the customer from the URL via `get_customer_or_404` (unknown and unauthorised are identical 404s). Since this review this happens in `CustomerScopedMixin.initial()`, *before* input validation. DB triggers reject cross-customer rows on observation tables | **`test_idor_sweep.py`** (all customer routes × all methods), `test_tenant_isolation.py`, trigger tests |
| Disclosure via errors/logs | B1, logs | Standard error envelope (no stack traces, SQL or vendor bodies); secret redaction of logs and audit metadata | `test_audit_and_errors.py` |
| Disclosure of vendor PII/secrets | B4 → DB | Dropped AssetInfo fields (owner, last logged-on user, product keys); notification text redacted (secrets, e-mail, `DOMAIN\user`); custom fields stored **only** if customer-approved, never credential-like names; policy `NotificationSettings`/profile `Settings` dropped | `test_device_details.py`, `test_vsa_adapter.py`, `test_patch_policies.py` |
| Disclosure of files | B1 | Reports and uploads in private volumes with opaque keys; every download re-authorised and audited; 24 h / 72 h purge | `test_reports.py`, `test_onboarding.py` |
| Disclosure of backups | B7 | Dumps encrypted to a public key while streaming; the private key is not on the host; checksums | local drill (`DEPLOYMENT.md` §8) |
| SSRF from the connector | B4 | Exact-hostname egress allowlist (server config plus hosts a super admin allows in the portal: DNS names only, no wildcards/IPs/local or reserved names, audited, re-checked on every request); resolved addresses checked against blocked/private ranges; GET-only exact path allowlist (writes, including device move, not allowlisted); fixture instances can never use the network | `test_vsa_adapter.py`, `test_connection_test.py`, `test_connector_hosts.py` |
| **D**enial of service | B1, B5, B4 | Upload limits (5 MB app, 6 MB proxy on one route, 1 MB elsewhere); max page size 200; report row limit; per-sync per-device budgets; vendor `Retry-After` honoured; no retry on 401/403; container log rotation | importer and budget tests |
| **E**levation of privilege | app | Capabilities per role from code; global-only capabilities never granted by membership; customer admins can delegate only engineer/viewer. Two-person approval for source mappings, catalog, patch baselines, health thresholds, expected subnets and custom fields; no self-approval. VSA device moves disabled (not implemented) | `test_admin_api.py`, approval tests, `test_idor_sweep.py::test_viewer_cannot_write…` |
| Container escape / host | deploy | Non-root images (uid 10001 / 101), read-only root FS, `cap_drop: ALL`, `no-new-privileges`; SELinux enforcing; DB/Redis on an internal network | config review only (**never booted**) |

## 3. Findings of this review and their resolution

| ID | Finding | Severity | Resolution |
|---|---|---|---|
| F1 | `POST /customers/<other>/memberships/` (and any create on a nested route) validated input **before** authorising the customer. It returned 400 instead of 404, which revealed that the customer exists and processed untrusted input pre-authorisation. No write occurred. | Medium | Fixed: `CustomerScopedMixin.initial()` authorises before any handler. A generic sweep test now covers every customer route and method |
| F2 | Three `assert` statements used as runtime checks (removed under `python -O`) | Low | Replaced with explicit exceptions |
| F3 | Dev-tooling advisories: vitest/@vitest/mocker (path traversal, code injection), tinypool (prototype pollution), minimatch (ReDoS). None ship in the production image. | Critical/Moderate (dev only) | Fixed: vitest 4.1.12; minimatch 11.0.8 override for typescript-estree; `npm audit` = 0 for all deps |
| F4 | Production secrets documented as root-owned `0600` would have been unreadable by the non-root containers (a deployment blocker) | High (availability) | Fixed earlier: `prepare-secrets.sh` (group-readable 0640, SELinux label) |
| F5 | `secrets/` was not git-ignored | High (if triggered) | Fixed earlier |

**Scanner results after fixes (2026-11-13):**

* bandit: 0 medium/high in 15.9k lines. Low-severity items are false positives: an error-message string, the fixture RNG, and XML escaping of output.
* semgrep `p/django p/python p/secrets p/typescript p/react`: 0 findings in 230 files. There is one parser warning on a literal `&` in JSX text, which is a tool limitation.
* pip-audit: no known vulnerabilities.
* npm audit: 0, all dependencies.
* shellcheck: clean.
* Django `check --deploy`: only `security.W008` (see section 4).

All of these now run in `.github/workflows/security.yml` (CI has not yet been executed: no remote).

## 4. Accepted design decisions

* **`SECURE_SSL_REDIRECT=False` (W008):** nginx redirects HTTP→HTTPS and is the only published service. Enabling the
  redirect in Django would break the container's internal HTTP health check. HSTS is on in production.
* **`CSRF_COOKIE_HTTPONLY=False`:** the SPA must read the token to send `X-CSRFToken`. Mitigated by `SameSite=Lax`, the
  same-origin design and the CSP (`script-src 'self'`).
* **`SameSite=Lax`, not `Strict`:** OIDC returns the browser via a top-level cross-site redirect to the callback.
* **All integration settings in the portal (decisions of 2026-11-13, interim DEC-07):** a super admin allows API hosts and enters every credential field in the portal. All credential fields of an integration are encrypted together as one blob bound to the integration and provider. Hostnames are not encrypted: they are not secret and are checked on every request. A super admin can therefore point a connector at any public host they allow; private/internal resolution stays blocked. A database dump alone does not reveal it; an attacker with both the database and the host key file (or code execution in the worker) does. `test_portal_credential.py`.
* **Saved views are writable with read access:** they are personal and owner-controlled, and editing another user's view is
  refused. This is the only viewer-writable route, explicitly allowlisted in the IDOR sweep.

## 5. Residual risks (open)

| ID | Risk | Rating | Mitigation in place | Recommended action |
|---|---|---|---|---|
| R1 | DNS-rebinding TOCTOU: the egress check resolves the host, then `requests` resolves again | Low | Exact hostname allowlist set by system admins; TLS verification (a rebind to an internal IP fails the certificate check for the vendor name); no redirects | Pin the validated IP in a custom transport adapter (keep SNI/hostname verification) |
| R2 | OIDC/MFA only tested against a mock IdP | Medium | Local login can be disabled; MFA is enforced by the IdP | Entra UAT (VSAP-01, BLOCKED_APPROVAL) |
| R3 | Vendor credential is entered in the portal (encrypted in the DB) or an `env:` reference; no vault | Medium | Fernet with a host-held key (`secrets/connector_encryption_key`, not in the DB or backups); bound to the integration id; write-only API; super admin only; audited without values; cleared when the base URL changes | Vault/KMS integration (DEC-07); protect the host and the key file |
| R4 | Container images not pinned by digest (`postgres:16-alpine`, `redis:7-alpine`, `nginx-unprivileged:1.27-alpine`, `python:3.12-slim`, `node:22-alpine`) | Low–Medium | Pinned minor lines; hash-pinned Python lock | Pin digests in the release build; scan images (e.g. Trivy) |
| R5 | Redis has no AUTH (internal network only) | Low | `data` network `internal: true`, protected mode | Add `requirepass` from a Docker secret |
| R6 | The deployment has never been booted; SELinux labels, firewall (DOCKER-USER) and permissions are unverified | Medium | Preflight script | First boot on an AlmaLinux test VM |
| R7 | App-level encryption of report/upload files not implemented | Low | Private volume, TTL purge, host disk encryption expected | Decide with DEC-07 |
| R8 | No independent penetration test; CI security jobs never executed | Medium | This review and the automated suites | External test before go-live; push to a remote and run CI |

## 6. Required before production (security view)

1. Run CI (`ci.yml`, `security.yml`) on a real remote and keep them green.
2. First AlmaLinux boot: run `preflight.sh`, and verify SELinux denials (`ausearch`), DOCKER-USER restrictions, and that
   the secrets are readable by the containers only.
3. Entra OIDC UAT with MFA; disable local login except approved break-glass.
4. Pin image digests and scan images; add Redis AUTH.
5. Independent penetration test covering IDOR, auth, uploads and SSRF.
6. Live VSA pilot (VSAP-04) with an approved read-only token, and a backup + restore drill on the host (VSAP-02).
