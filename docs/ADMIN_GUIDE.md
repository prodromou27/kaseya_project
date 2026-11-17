# Administrator guide — intended workflows

## Remediation rollout notes — 2026-11-14

The internal group-move workflow adds `customer.group_move.propose` (engineer/admin/global admin) and `customer.group_move.approve` (customer/global admin). A reviewer must differ from the proposer even when legacy single-admin catalog approval is enabled. Proposed content and final decisions are database-immutable and audited. There is no execute action or vendor write credential in this implementation.

Apply additive inventory migrations `0009_group_move_proposals` and `0010_guard_group_moves` with the API/worker release. The preferred application rollback retains these tables to preserve proposal/audit history. Review [deployment and rollback](CODEX_DEPLOYMENT_AND_ROLLBACK.md), [security gates](CODEX_SECURITY_REVIEW.md) and [actual verification](CODEX_VERIFICATION.md) before an approved staging rollout.

`benchmark_inventory` (add `--related` for software/patch/server data, see `CODEX_PERFORMANCE.md`) is a development-only synthetic tool, restricted to a new `bench_*` database and explicit acknowledgement. Never run it against the application database. The QA-only login throttle override used in browser tests is not a production recommendation.

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

**From the VSA application catalog (CAT-01).** Settings → Software catalog → *Import from the VSA application catalog*: open the [VSA 10 application catalog](https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm), select and copy the whole table, paste it and choose *Match installed programs*. The portal keeps only catalog programs installed on monitored devices (names matched after removing editions such as "(64-bit)"/"x64"), skips discontinued entries, non-numeric versions and programs whose 32-bit and 64-bit catalog versions differ, and leaves out programs whose published reference is already that version. Check *Installed versions* against the catalog version (a warning appears when most installs report a higher version, which usually means a different version format), submit, and have a **different** administrator approve. The evidence link is the catalog page and the source type `vsa_application_catalog`. Re-paste after the catalog's monthly update to move references forward. The catalog version is what VSA's 3rd-Party Patching deploys, which can trail the vendor's newest release. The VSA X API offers no catalog endpoint, so nothing is fetched automatically.

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
5. **Catalog:** Administration → Software catalog. Paste the VSA application catalog table and match installed programs (section 7), or paste JSON rows under *advanced*; run the preview, then submit. A **different**
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
19. **Integrations (all settings in the portal):** Admin → Integrations lists every integration with its status
    (available or planned) and what it needs. For VSA X: (1) *Allowed API hosts* → add your VSA hostname, e.g.
    `yourcompany.vsax.net` (DNS names only; private/internal names and IPs are refused); (2) add the integration with
    base URL `https://<that host>`; (3) *Set credentials*: token ID and secret of a **read-only** VSA X API token;
    (4) *Test connection*; (5) *Discover orgs* and map them; (6) *Enable*. *Edit* changes the name, base URL, request
    rate and budgets; a new base URL removes the stored credentials. Credentials are encrypted, can never be displayed
    again and can only be replaced or removed. Only super admins can do this; every change is audited (never values).
20. **Lifecycle (end of support):** Admin → *Lifecycle catalog* → propose an entry per OS release or software
    version line, citing the vendor's official lifecycle page (https) and the date you checked it. A different super
    admin approves it. Approved entries cannot be edited: retire and propose a corrected one. Use *secondary*
    confidence for anything not from the vendor; such entries never classify devices. Engineers see the result under
    *Lifecycle (end of support)* and in report R17; devices without an approved official entry show as **unknown**.
21. **Connect VSA (recommended setup):** Dashboard → *Connect VSA* (or Settings → Integrations → *Connect VSA*):
    enter the VSA X address and a read-only API token ID and secret, then tick the organisations to bring in, each as
    a new customer or into an existing one. The portal allows the host, stores the token encrypted, tests the
    connection, approves the mappings, enables the integration and starts the first sync. Approved mappings sync
    daily (`SYNC_DEFAULT_INTERVAL_HOURS`); change the interval under Settings → Sync schedules.
22. **One administrator:** by default an administrator may approve their own catalog, lifecycle, threshold, subnet,
    baseline and custom-field changes (audited). Set `REQUIRE_SECOND_APPROVER=true` in `.env.prod` to require a
    second administrator.
23. **Sync troubleshooting:** `docker compose -f compose.prod.yml --env-file .env.prod exec backend python manage.py
    sync_status` lists integrations, mappings, schedules, recent runs and the worker, and ends with findings. A run
    that stays *queued* more than 10 minutes without starting is re-sent automatically on the next Sync now or
    schedule tick.
24. **Which data does VSA X return?** `... exec backend python manage.py vsa_probe` (optional `--integration NAME`,
    `--org ID`, `--devices N`) makes about five read-only GET calls with the sync's own request and lists, for a few
    devices, which sections came back (InstalledSoftware, AvailableUpdates, Disks, Security, …) with their field
    names and item counts, plus the per-device detail calls. It never prints values or credentials and is audited
    (`integration.probe`). An empty page in the portal plus "missing on every sampled device" here means VSA X did
    not return that data (agent setting or token permission), not a portal fault.
25. **System status:** Settings → System status (super admin) shows whether the background worker and queue are
    healthy, syncs in the last 24 h and their failure causes, customers whose data is out of date, export volume
    and failed sign-ins. It refreshes every minute; a red banner appears on the dashboard when something is broken.
    It reads only the portal's own database and makes no VSA X calls.

## Onboarding agent groups and CIDR suggestions

CIDR-02 adds a paginated suggestion list directly to marked onboarding groups. Explicit approved destination CIDRs outrank networks observed on destination peers; naming tokens are weaker evidence. Review the labelled basis and competing candidates before manually transferring an agent. Observed networks are not an approved policy. No additional migration is needed; ONBOARDING_SUGGESTIONS.md records the behavior and verification.

Open Groups & network, choose the source-qualified group and enable **Use as an onboarding group** to identify a generic installation destination. This audited setting uses customer.manage_exceptions and does not change VSA. A temporary onboarding assignment is valid; the administrator decides when to transfer the agent manually.

On each eventual destination group, use **Propose subnet** to add one or more strict IPv4/IPv6 CIDRs with a reason. A different administrator approves each rule under the existing review policy. New rules carry the group's VSA instance identity. Retire outdated rules. Device Operations shows matching approved group rules, addresses and ambiguity; selecting a suggestion only fills the proposal target. Site expectations and unqualified legacy rules do not generate destination suggestions. See ONBOARDING_GROUPS.md for rollout/rollback limits.

## Saved device layouts (LIST-01)

Apply reporting migration 0003_saved_view_layout before the new backend. Existing filter-only views remain valid. Any authorized customer reader can save a private personal view; sharing is explicit, and only its owner may update/delete it. Layout changes are validated and CRUD audited. Normal reports retain their defined columns and existing export capabilities. Prefer application rollback retaining the additive layout field; see LIST_USABILITY.md for the tested migration path and remaining deployment gates.

## Investigation lists and coverage exports (LIST-02)

No additional migration is required. The new os_update_coverage report uses existing read/export capabilities, protected artifacts, audit and retention; its rows distinguish collection evidence from update records. Pinned source identity/timestamps are included. Before application rollback to an older report registry, pause coverage schedules and archive/manage coverage definitions while retaining artifacts and audit. See INTELLIGENCE_LISTS.md for verified scope and evidence. Named saved layouts remain a Devices feature.

## Enabling execution of approved group moves (VSA5-EXEC)

Off by default. All three are required; removing any one switches execution off again.

1. Create a **separate** VSA X API token for moves (not the read token), with the narrowest permissions VSA X allows.
2. Store it on the host as a Docker secret / environment value named `VSA_WRITE_<NAME>` in the form
   `TOKEN_ID:TOKEN_SECRET` (for example `VSA_WRITE_PROD`, or `VSA_WRITE_PROD_FILE` pointing at the secret file).
3. Set `VSA_GROUP_MOVE_EXECUTION_ENABLED=true` in the server environment and restart the web and worker containers.
4. In **Settings → Integrations → Edit**, tick *Allow approved moves to be executed for this integration* and enter the
   write token reference `env:VSA_WRITE_<NAME>`. The change is audited. Changing the integration's base URL clears the
   switch.

Optional: `GROUP_MOVE_EXECUTION_WINDOW_HOURS` (default 24) limits how old an approval may be when executed. Audit
events: `group_move.execute_started`, `group_move.execute_succeeded|unverified|unknown|failed`, `group_move.verified`.
Validate on one test device first (live behaviour has not been verified yet).

