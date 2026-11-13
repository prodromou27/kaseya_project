# Administrator guide — intended workflows

**Status:** Functional specification for the portal administration UI and runbooks. Screen labels/routes are targets until implemented. Do not use this as a claim of deployed functionality.

## 1. Responsibilities and roles

- **Super administrator:** instance settings, identity and security policy, integration credential references, global customer mappings, audit access.
- **Administrator:** scoped customer setup, engineer memberships, source-to-customer mapping review, schedules/catalog approvals within delegated rights.
- **Engineer:** authorized customer read/search/report and manual read-only sync if permitted.
- **Viewer:** assigned customer read access; exports only with explicit permission.

Every administrative change must produce an audit event with actor, target, timestamp, before/after-safe summary, and outcome.

## 2. Initial application provisioning

1. Verify infrastructure/TLS/backup prerequisites from `DEPLOYMENT.md`.
2. Complete migrations and create the **one-time local bootstrap administrator** on the management network.
3. Register Microsoft Entra OIDC client; configure redirect/logout URLs, issuer, audience, trusted certs, MFA policy.
4. Test SSO with a nonadmin user and audit events. Disable/restrict local auth and revoke/rotate bootstrap credentials.
5. Set approved retention policy, report artifact storage, SMTP (optional), timezone, source freshness thresholds and alert channels.
6. Validate each role against access matrix in `SECURITY.md` before onboarding real data.

## 3. Onboard a new customer

1. Open **Administration → Customers → Add customer**.
2. Record customer code, name, status, data-processing approval reference, permitted retention and hosting classification.
3. Assign engineers/viewers with minimum required permissions.
4. Select integration instance(s) and retrieve available source organizations **without importing customer data**.
5. Map exact source organization IDs. Record reviewer and approval. Never map only on fuzzy name similarity.
6. Run a **preview/dry-run** that estimates asset count, API request budget and excluded/missing mappings.
7. Authorize an initial **read-only** sync and verify asset counts directly against source UI; mark customer active only when validation succeeds.
8. Generate first inventory report, review source timestamp and document acceptance.

Government/CYTA and other restricted customers require specific approval, potentially a separate instance. Never assume the central Odyssey portal is an approved data destination.

## 4. Configure VSA X integration

1. Generate a vendor API token under a dedicated service identity using applicable minimum permissions.
2. In **Integrations → Add VSA X**, choose supported HTTPS base URL, credentials reference, trust chain, and approved egress range.
3. Test authentication using a harmless documented GET with bounded requests.
4. Check accessible organization IDs, review allowed customer mappings, select data sections (`InstalledSoftware`, `AvailableUpdates`, etc.) and max concurrent requests.
5. Define sync frequency from the observed request budget; monitor 429 and latency.
6. Test one pilot customer against VSA UI results and confirm installed software/version consistency.
7. Enable the schedule only after signed-off validation.

If a connector reports unauthorized or TLS failures: suspend only that integration, preserve last published data, and show stale status. Do not disable TLS verification.

## 5. IT Glue integration

Choose the **actual account region**: US/EU/AU official endpoint. Configure `x-api-key` through vault reference. Restrict dataset to organizations and explicitly approved configuration fields. **Passwords and secret resources remain excluded.** Review source org mappings and run a preview before importing.

## 6. Autotask PSA integration

Configure API-only resource credentials and integration code; discover correct zone as documented. Confirm that API security level is copied and restricted, not an unrestricted default unless there is a documented approved exception. Restrict to company and ticket metadata. Reconcile company IDs to customer mappings and sample-compare counts with PSA UI.

## 7. Software catalog review

1. Import a catalog spreadsheet with `vendor`, `product`, `edition`, `channel`, `architecture`, `reference_version`, `source_url`, `verified_at`.
2. Review proposed aliases and collision warnings.
3. Verify the reference source and release channel. Make a revision immutable once approved.
4. Preview impact: which existing installations change classification, how many become unknown/newer/outdated.
5. Approve/reject and publish with named reviewer and audit record.
6. Re-run compliance calculations asynchronously for affected approved customers only; preserve older reports and catalog revision links.

A catalog update never means the portal is deploying a patch.

## 8. Manage schedules and reports

- Define schedules per customer and dataset, with timezone and rate-budget estimates.
- Require completed source snapshot for formal reports; if stale datasets are permitted for investigative reports, watermark them.
- Confirm recipient/customer authorization, report retention and export policies.
- Review failed runs and retry under idempotency control; do not create unbounded duplicate schedules.

## 9. Troubleshooting quick table

| Symptom | Investigation | Safe action |
|---|---|---|
| VSA 401 | Token/permissions/endpoint | Review identity/secret ref; stop retries |
| VSA 429 | API budget and `Retry-After` | Throttle or defer; preserve last snapshot |
| Missing customer assets | Source mapping, rejected/quarantined rows, pagination | Correct mapping and rerun approved preview |
| Wrong software comparison | Alias/channel/architecture/catalog revision | Mark unknown, review reference, reclassify |
| Empty PSA tickets | API user rights, zone and mapping | Verify permissions in test scope |
| Report download denied | Customer membership/retention expiry | Reauthorize, do not bypass RBAC |
| PostgreSQL unavailable | DB health, storage, migrations | Follow restore/incident runbook |

## 10. Operational governance

Weekly: failed sync review, quarantine mappings, stale dataset queue. Monthly: role membership and customer mapping review, catalog source review, backup health and report-retention audit. Quarterly: access review, restore exercise, vulnerability/dependency scans, least privilege validation and capacity trends (frequency subject to internal policy).


## Implemented operations (P0–P1, 2026-11-12)

1. **Bootstrap:** `python manage.py bootstrap_admin --email <you>` (one-time; the password comes from `BOOTSTRAP_ADMIN_PASSWORD`).
2. **Connector:** Administration → Integrations. Set the host in `CONNECTOR_ALLOWED_HOSTS_VSA_X` first, then add the instance
   with `credential_ref = env:VSA_TOKEN_<NAME>` (the environment or secret file holds `TOKEN_ID:TOKEN_SECRET`), then enable it.
   TLS verification cannot be disabled.
3. **Mapping:** use "Discover orgs" to list source organisations. A customer admin proposes a mapping using the **organisation ID**,
   and a super admin approves it under Administration → Mapping review. Unmapped organisations are never collected.
4. **Sync:** Assets → "Sync now (read-only)". Check freshness under Data sources. Investigate quarantined records under
   Administration → Sync quarantine.
5. **Catalog:** Administration → Software catalog. Paste the JSON rows, run the dry-run preview, then submit. A **different**
   administrator approves. Published revisions are immutable.
6. **Exceptions:** customer admins add time-limited, justified exceptions on the Software versions page.

### Added in P2

7. **Installed updates:** set "InstalledUpdates budget / sync" on an integration (per-device calls per sync). Leave it at 0 until
   the API budget has been measured in a pilot. Devices outside the budget show *carried forward* or *not requested*.
8. **Scheduled syncs:** Administration → Sync schedules (approved mappings only). Requires the `beat` service in Compose.
9. **Report schedules:** Reports → Definitions & schedules. Delivery is in-portal only (DEC-09). Recipients must currently have
   export access. Anyone who loses access is removed at the next run, and this is audited.
10. **Retention:** report files are deleted after `REPORT_ARTIFACT_TTL_HOURS` (hourly purge job). Dataset generations are kept
    until a retention policy is approved.

### Added in VSA Phase 1 (fixture-tested)

11. **Onboarding uploads:** files live on the private `onboarding` volume (`ONBOARDING_STORAGE_DIR`). They are purged
    after `ONBOARDING_UPLOAD_TTL_HOURS` (default 72) by the hourly `purge-expired-onboarding-uploads` beat job.
    `ONBOARDING_MAX_UPLOAD_BYTES` (default 5 MB) must stay below the proxy's per-route limit (6 MB on the upload route
    only; every other route keeps the 1 MB limit). `ONBOARDING_MAX_ROWS` defaults to 20,000. Comparisons run on the
    `reports` queue.
12. **Snapshot requirement:** a comparison needs a current sync with a complete site/group crawl. If the hierarchy step
    failed, re-run the sync. The previous good generation stays current meanwhile, but it cannot be compared until the
    hierarchy is complete.
13. **Applied policies budget:** Administration → Integrations, "Applied policies budget / sync". Each unit is one
    `GET /devices/:id/appliedpolicies` call (documented limit 3600 per hour). Start at 0 until the pilot has measured
    the API budget. Devices outside the budget carry forward their last response, or stay *unknown*.
14. **Expected patch policies:** Patch policies → *Expected policies*. A customer administrator proposes an
    expectation for an organisation, site or group, and a **different** administrator approves it. Retire an
    expectation to stop it driving drift. Every step is audited.
15. **Health thresholds:** Device health → *Thresholds*. A customer administrator proposes the offline hours, stale
    days, disk warning and critical percentages, and an optional minimum agent version; a **different** administrator
    approves. The documented defaults (24 h, 7 days, 15 %, 5 %, no minimum) apply until then and are labelled as
    defaults. Approving a new proposal supersedes the previous thresholds, and the history is kept. Without an approved
    minimum version, agent age is *not evaluated*.
16. **Connection test:** Administration → Integrations → *Test connection*. It makes one read-only
    `GET /api/v3/ratelimits` call, then shows the outcome, latency and per-endpoint remaining/limit values; use these
    to size the per-sync budgets. An invalid token shows `auth_failed` and is never retried. Fixture instances show
    the documented example. The last result is stored on the integration, without credentials.
17. **Expected subnets:** Groups & network → a group → *Network review*. A customer administrator proposes a subnet for
    the group or its site, and a **different** administrator approves it. Addresses outside approved subnets are
    review flags, not proof of misconfiguration. Addresses of an IP version with no expectation are *not evaluated*.
18. **Notifications and custom fields:** set "Notifications budget / sync" (and "Custom fields budget / sync") on the
    integration. Notifications older than `NOTIFICATION_WINDOW_DAYS` (14) are not stored, and message text is redacted
    before storage. Custom fields are read **only** for names approved on Customer → *Custom fields* (customer admin
    proposes, a different admin approves). Names that look like credentials are refused and never stored.
19. **VSA X API token:** Admin → Integrations → add the VSA X integration (base URL `https://<vsa host>`; the
    host must be allowed on the server: `sudo ./install.sh --vsa-host <host> -y`). Then *Set API token*: enter the
    token ID and secret of a **read-only** VSA X API token, save, and run *Test connection*. The token is encrypted
    and can never be displayed again; *Replace API token* or *Remove token* are the only actions. Changing the base
    URL removes it. Only super admins can do this, and every change is in the audit log (never the value).
