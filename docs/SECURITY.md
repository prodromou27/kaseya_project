# Security architecture and acceptance controls

**Security stance:** This application contains potentially sensitive customer operational data. Read-only upstream APIs do not make exposure harmless. **Never use production customer data without legal, contractual and security approval.**

## 1. Threat model

> **As implemented (2026-11-13):** see [THREAT_MODEL.md](THREAT_MODEL.md) for the STRIDE review, scanner results, fixed findings, accepted design decisions and open residual risks.

Assets: vendor API credentials, customer topology/hostnames/software, ticket metadata, report artifacts, user sessions, catalog approvals, and audit evidence.

Threats: cross-customer data leakage, IDOR, privilege escalation, stolen connector credentials, query injection/SSRF, hostile source data (stored XSS, CSV injection), exposed exports, poisoned software reference versions, incorrect patch/compliance claims, job queue replay, supply-chain compromise, unmonitored or untested backups.

Trust boundaries: user/browser ↔ portal; portal ↔ IdP; portal ↔ workers/storage; collectors ↔ vendor APIs; portal ↔ private exports.

## 2. Identity, RBAC and customer isolation

- Production: Microsoft Entra ID OIDC with policy-enforced MFA; validate issuer, audience, state, nonce and token signatures using trusted OIDC discovery/JWKS.
- Bootstrap admin: local only for initial provisioning/dev; configurable one-time enablement, rotated strong password, restricted network. Disable after SSO verification.
- Roles: `super_admin` (all customers plus system), `admin` (delegated admin scope), `engineer` (assigned customer read/report), `viewer` (assigned customer read, export only if granted).
- Every object access must resolve customer from database records and check membership; never trust `customer_id` supplied by the client without authorization.
- Test cross-customer exposure through: list, object detail, search, report filters, scheduled jobs, file artifact URL, API errors, admin selectors, and notification distribution.
- Source connector credential scope does **not** grant portal user access. Unknown external organization IDs go to quarantine.
- PostgreSQL row-level security may add defense-in-depth, but does not replace Django policy checks. If used, prove worker/session context correctness through tests.

## 3. Secrets and connector egress

- Use an approved vault/KMS or encrypted application secrets with separately managed encryption key; env vars only as startup bootstrap pointer, not long-term secret catalog.
- Never include credentials in migration files, test fixtures, screenshots, logs, reports, or exceptions.
- Connector configuration: allowlisted HTTPS hostnames and ports. For on-prem VSA instances, explicit administrator-approved internal host/IP CIDR ranges; do not let ordinary users set target URLs.
- Resolve DNS safely, block unsafe redirects/destination IPs unless explicitly approved, and reject URL userinfo, unusual schemes and TLS bypass.
- Require certificate validation against trusted CA; install internal CA into containers if needed; do not use `verify=False` or `curl -k`.
- Integrations use read-only access with least privilege. Where vendor token privileges cannot be restricted, limit network egress and exposed query fields; record residual risk.
- **Single exception (ADR-029, VSA5-EXEC):** executing an *approved* VSA X group move (`PUT /api/v3/devices/{id}/move`). It lives in its own module (`apps/integrations/vsa/writer.py`), never in the read client, and is off unless all three are set: server switch `VSA_GROUP_MOVE_EXECUTION_ENABLED=true`, the integration's "execute approved moves" switch (super admin, audited, cleared when the base URL changes) and a token: the integration's API token, or an optional separate write token (portal-entered, encrypted, or `env:VSA_WRITE_<NAME>`). Product owner decision 2026-11-18: one token is accepted; the residual risk is that the token used for reading can also change VSA X, so restrict its VSA X permissions to what is needed and keep the switches off when unused. One attempt per proposal, committed before sending; no retries; timeouts/5xx are recorded as unknown and resolved only by reading the device back. Use a VSA X token whose permissions are limited to device moves where VSA X allows it.

- **Public catalog read (ADR-030, CAT-02):** the worker makes one daily HTTPS GET of the fixed VSA 10 Application Catalog page (https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm) - no credentials, verified TLS, no redirects, 5 MB cap, destination must resolve to a public address. The URL is a code constant, not configurable. Requires outbound HTTPS to `help.vsa10.kaseya.com`; off with `VSA_APP_CATALOG_AUTO_UPDATE=false`. Version increases for already-approved catalog products are published without a second person (audited); everything else stays in review.

- **Second exception (ADR-031, CFA):** assigning or updating a VSA X custom field on a workstation (`POST /api/v3/[automation/]customfields/{id}/assign`, `PUT …/updateAssigned`, body `ContextType: Device`). Separate module (`apps/integrations/vsa/cf_writer.py`), off unless the integration switch, a route validated on a test workstation and a token are all present (set up by a super admin in the portal; the integration's API token is used unless an optional separate write token is set, which is Fernet-encrypted, write-only, bound to the integration and the purpose "write", and cleared when the base URL changes), and blocked entirely by the server emergency stop `VSA_CUSTOM_FIELD_WRITES_ENABLED=false`. Only customer administrators and super admins apply jobs; engineers prepare and preview. Field and device IDs are only ever looked up within the URL's customer and its mapped integrations; identifiers and values are validated before any request; OData filters are built from validated IDs only. Uploaded lists use the hardened importer (macros, embedded objects, DTDs and zip bombs refused, formulas never evaluated); reports are formula-neutralised. Every request, confirmation, approval and per-device result is audited with previous, requested and final values.

## 4. Web/API protections

- Secure, HttpOnly, SameSite cookies; CSRF for cookie-authenticated mutation endpoints; explicit CORS allowlist (or same origin).
- Short-lived sessions, idle timeout, logout/revocation, no sensitive data in browser localStorage.
- DRF permission classes + queryset scopes; prohibit unrestricted raw SQL on user input; parameterize queries.
- Input limits and validation for filters, pagination, sorting, filenames and report templates.
- Escape/sanitize source-controlled text in UI and HTML/PDF templates. HTML from vendor notes must not be rendered unsanitized.
- Prevent CSV formula injection for cells starting `=`, `+`, `-`, `@`, tab or CR, including Excel exports; test formulas.
- Harden report download with fresh authorization and short-lived storage access. Never return raw server filesystem paths.
- Login/API rate limiting; payload size limits; safe error messages; security headers (HSTS, CSP, frame policy, content-type nosniff).

## 5. Audit and observability

Append audit for login/logout, failed authorization, customer grants, connector edits, catalog revision approval, sync starts/stops, reports generated/downloaded, storage purge, and system settings. Event fields: `event_id`, UTC timestamp, actor, customer, source, action, target, outcome, request ID; do not log source secrets or entire personal-data objects.

Make audit records immutable to ordinary users and append-only at application role level; forward to an approved central log system and retain under policy. Local database-only audit is not inherently tamper-proof. Alert on repeated 403s, sync failures, mass exports, unapproved mapping changes, and credential errors.

## 6. Data handling and contractual scope

Maintain customer-by-customer data-processing approval, region/residency, retention, permitted fields, incident notification owner, and external processing restrictions. **Government of Cyprus/CYTA data must not be automatically ingested into the Odyssey-wide portal**: its project documents impose Cyprus/site and approval constraints; use a separately approved deployment/path if allowed.

Store minimum required asset/software/ticket metadata. IT Glue password and secret resources are forbidden. Limit ticket descriptions and personal data. Prefer links to vendor records rather than full confidential document copies.

## 7. Backups, recovery and secure deletion

- PostgreSQL logical or physical backups and report artifacts protected by encryption at rest and in transit.
- Encrypted off-host copies and secrets/key recovery handled separately.
- Define RPO/RTO before go-live; test isolated restoration, sample report regeneration, role mapping and audit continuity.
- Schedule retention/purge for observations, exports and logs; log deletion actions; define legal hold.
- For restore drills, never use real data in an unsecured test environment.

## 8. Supply chain, container and host security

- Pinned dependencies with lock files, SCA/secret scanners, signed/verified base images where feasible.
- Images run non-root and read-only FS where supported; drop Linux capabilities; no privileged Docker socket mount.
- PostgreSQL/Redis internal networks only; strict firewall; restrict admin access via VPN/jump hosts.
- AlmaLinux SELinux enforcing; compose volume labels and permission model validated.
- Production TLS from approved certificates; security patches and maintenance process documented.

## 9. Security gate checklist

- [ ] Customer data handling and permitted location approved.
- [ ] Entra OIDC configured, MFA verified, local bootstrap disabled/restricted.
- [ ] All tenant IDOR/export/background job negative tests pass.
- [ ] Vendor credentials readonly where possible; no secrets in logs.
- [ ] Egress allowlist, TLS chain, SSRF controls validated.
- [ ] Source data sanitization and CSV/XLSX injection tests pass.
- [ ] Report retention/encryption/access revocation validated.
- [ ] Central audit forwarding and alerts validated.
- [ ] Restorable off-server encrypted backup demonstrated.
- [ ] Dependency vulnerability scan and production configuration review pass.
