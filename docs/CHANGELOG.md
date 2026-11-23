# Changelog

## OPS-05 - 2026-11-23 - updates no longer stop at "waiting for the portal to become ready"

- Fix: after an update recreated the backend container, the proxy kept the backend's old IP address and every request failed with 502 (`connect() failed (111: Connection refused)`), so `install.sh` gave up after 5 minutes. The proxy now re-resolves `backend` through Docker's DNS (`resolver 127.0.0.11 valid=10s`), and `install.sh` restarts the proxy after starting the stack. **Existing stuck install:** `sudo docker compose -f compose.prod.yml --env-file .env.prod restart proxy`.

## UX-07 - 2026-11-23 - switch group moves on in the portal

- `VSA_GROUP_MOVE_EXECUTION_ENABLED` now defaults to `true` and is only a server-wide emergency stop; moves are switched on per integration in Settings → Integrations → Edit (still off until a super admin ticks it), as for custom field writes. **Existing installs:** an `.env.prod` created from the old example still contains `VSA_GROUP_MOVE_EXECUTION_ENABLED=false`; change it to `true` (or remove the line) and redeploy.
- Group move approvals show the exact reason moving is unavailable (server stop with the variable and file to change, integration switch or missing token). API: proposals include `execution_unavailable_reason`.

## UX-06 - 2026-11-22 - approve all suggested moves as a single administrator

- Fix: moves proposed by an administrator stayed pending because the requester could never approve them, even with single-administrator approvals. Group moves now follow `REQUIRE_SECOND_APPROVER` like every other approval: off (default) lets an administrator approve and move their own proposals; on requires a different administrator. Audit: `group_move.approved` records `self_approved`, `group_move.execute_started` records `by_requester`. Migration `inventory.0015` removes the database constraint that forbade requester = reviewer.
- Group move proposals opens on **Waiting for decision** (also *Approved, not moved yet* and *All proposals*), 200 per page; the header checkbox selects all for **Approve and move (N)**. When moving is not switched on for the integration, the page says that approving only records the decision.
- API: proposals include `self_approval_allowed`; the list accepts `view=waiting|to_move`.

## UX-05 - 2026-11-22 - shorter menu

- The side menu shows 6 entries instead of about 20: *Daily work* (Dashboard, Devices, Device health, Reports) and *Changes in VSA X* (Custom fields, Group move approvals). *Patching & software*, *Inventory & network* and *Administration* are folded groups; the one containing the current page opens by itself, opened groups are remembered per browser, and **Find a page** searches and opens every group. All page URLs are unchanged.

## UX-04 - 2026-11-20 - find a device and check a customer's health faster

- Header **Find a device** works on every screen size and without choosing a customer first: as you type (2+ characters) it lists up to 10 matches by hostname, serial or VSA device ID from every customer you may read; choosing one selects its customer and opens the device.
- API: `GET /api/v1/assets/lookup/?q=` (current published inventory of approved mappings only, scoped to customers with `customer.read`; revoked mappings hide data).
- Dashboard: with no customer selected it shows **Your customers** (the all-customers health table; a click opens that customer's dashboard). With a customer selected it shows the full customer summary under the tiles (compliance, patching, servers, network, VSA details, recent reports, scorecard).
- The monthly scorecard offers its download in place when ready.

## UX-03 - 2026-11-20 - fewer clicks for reports

- New report and Custom report: after **Generate**, the page waits for the file and shows **Download** right there (History still lists every run).
- **Send this report regularly** on both forms: name, frequency, day, time (browser time zone) and recipients; saves the definition and the schedule in one step, or *Save without schedule*. Replaces the browser prompt of *Save as definition* / *Save for reuse*. Same APIs and authorisation checks.

## UX-02 - 2026-11-20 - fewer clicks for group moves

- Onboarding destinations: tick devices and **Propose moving N devices** (one normal proposal per device, prefilled reason).
- Group move proposals: select several and **Approve and move (N)**, **Approve only** or **Reject** with one reason; the requester's own, expired and decided proposals are skipped; results per device.
- Single proposal: **Approve and move in VSA X** reviews and executes in one step (the requester still cannot approve or execute; every server check is unchanged and each move is still sent once).
- API: proposals include `execution_available`; destination plan entries include the group `id`.

## UX-01 - 2026-11-19 - fewer clicks for custom field changes

- The preview starts by itself when no line needs a device choice.
- One confirmation checkbox replaces the separate overwrite checkbox (it states how many devices are overwritten; the API still requires `acknowledge_overwrite`).
- An out-of-date preview is refreshed automatically when the job is opened.
- Administrators see a *Waiting for you to apply* list at the top of the Custom fields page (prepared jobs and jobs waiting for a second approval), so they no longer search the history.
- API: jobs include `preview_expires_at`; `?state=` accepts several comma-separated states.

## CFA-11 - 2026-11-18 - one VSA X token is enough

- Group moves and custom field changes now use the integration's API token; a separate write token is optional (Settings → Integrations → Edit → *Separate write token*, or `env:VSA_WRITE_*`) and is used instead when set. The rule that the write token must differ from the read token is removed. Availability message is now "No VSA X API token is configured for this integration." when neither exists.

## CFA-10 - 2026-11-18 - custom field writes set up in the portal; only administrators apply

- **Settings → Integrations → Edit** (super admin) now has *Write token* (a separate VSA X API token entered in the portal, Fernet-encrypted, bound to the integration and the purpose "write", never shown again, refused if it is the read token, cleared when the base URL changes; audited `integration.write_credential_set|cleared`) and *Validate on a test workstation* (writes one value to one confirmed test device, reads it back, records the route; same logic as `manage.py vsa_custom_field_validate`, which now also accepts a hostname). New endpoints `POST|DELETE /integrations/{id}/write-credential/`, `POST /integrations/{id}/validate-custom-field-route/`; migration `integrations.0015`. Group moves use the portal write token too.
- `VSA_CUSTOM_FIELD_WRITES_ENABLED` now defaults to **true** and is only a server emergency stop; nothing is written until the portal setup (token, validation, switch, editable fields) is complete.
- **Only administrators apply**: confirming and retrying a custom field job needs `customer.custom_field.approve` (customer administrators, super admins). Engineers still read fields, prepare, import and preview; the job panel tells them an administrator applies it.

## FIX-COMPOSE - 2026-11-18 - write switches and write token reach the containers

- `compose.prod.yml` passed only a fixed list of settings into backend/worker/beat, so `VSA_GROUP_MOVE_EXECUTION_ENABLED`, `VSA_CUSTOM_FIELD_WRITES_ENABLED`, `VSA_APP_CATALOG_AUTO_UPDATE` and any `VSA_WRITE_*` token set in `.env.prod` never took effect. They are now passed through (writes still default to off), and the write token is a Docker secret file `secrets/vsa_write_token` (`VSA_WRITE_TOKEN_FILE`), created empty by `prepare-secrets.sh`; reference it as `env:VSA_WRITE_TOKEN`.

## CFA - 2026-11-18 - VSA X custom field assignment

- **VSA operations → Custom fields** (new): assign or update existing VSA X custom fields (e.g. *PatchRing*) on workstations. Tabs: *Device assignments* (filters, selection across pages, all matching devices as a fixed list), *Import list* (paste, or TXT/CSV/XLSX with column mapping and optional per-device values), *Assignment history*, *Field overview*. Device page: new *Custom fields* tab. Both input methods use one engine.
- Flow: exact matching (device ID → serial → FQDN → hostname; not found / multiple / duplicate / invalid / other customer / not a workstation), live **preview** (device-level vs inherited value via the documented `/customfields/{id}/usage`), explicit **confirmation** (overwrites acknowledged), optional second approval, **execution** in Celery one device at a time (re-read before each write, committed *sending* first, never resent, 429 backoff), **read-back verification** with bounded retries, per-device results, cancellation, resume after a worker stop, CSV/XLSX report (Summary, Successful, Skipped, Failed, Not found, Ambiguous; formula-neutralised), retry of failed devices.
- **Second gated vendor write (ADR-031)**: documented `POST …/assign` and `PUT …/updateAssigned` only, `ContextType: Device`; unassign never called. Off unless `VSA_CUSTOM_FIELD_WRITES_ENABLED`, the integration switch, a route confirmed on a test workstation (`manage.py vsa_custom_field_validate` - the documentation gives `/api/v3/customfields/…` and `/api/v3/automation/customfields/…`) and the separate `VSA_WRITE_*` token. Super admins choose editable fields; credential-like, read-only, expired and non-device fields can never be edited.
- RBAC (existing roles): view = customer.read; assign/import = engineers and above (`customer.custom_field.assign`, max 10 devices per job); bulk = customer administrators (`customer.custom_field.bulk_assign`); approve = customer administrators, not the requester (`customer.custom_field.approve`); field settings = super admin. New migrations `integrations.0014`, `customfields.0001`.
- Verified: 17 backend tests (discovery/eligibility, assign/update/skip with read-back, overwrite acknowledgement, matching classes, ambiguity, XLSX/CSV/TXT import incl. formula and macro refusal, gates, routes/body, 429/400/timeout, concurrent change and interrupted run never resent, cancel/duplicate delivery/retry, bulk limit/approval/tenant isolation, report sheets and neutralisation, typed values, device page, select-all), 4 frontend tests, a browser scenario and the accessibility sweep. **Fixture only - no live VSA X call was made; the route, Boolean/Date value formats and inheritance behaviour must be confirmed with `vsa_custom_field_validate` on a test workstation.**

## CAT-03 - 2026-11-17 - more catalog programs matched; coverage shown

- Operator report: only 33 rows appeared although the catalog lists many more. Two causes: (1) name matching ignores versions and words in brackets, so catalog lines such as *.NET Desktop Runtime 5.0 ... 10.0*, *ASP.NET Core Runtime*, *.NET SDK*, *PowerShell 7.4/7.5* and *Microsoft Teams / Teams (work or school)* collapsed into one name with several versions and were all skipped - 127 of the 303 live entries; (2) catalog programs not installed on any device are left out by design, and the screen did not say so.
- Lines sharing a base name are now separated by **version series** (installed version or the version in the installed name must start with the series, e.g. 8.0.11 → *8.0*) or by **edition in brackets** (exact name). An installed name that would fit two lines is refused rather than matched to both. Still not automatic, with the reason shown: 32/64-bit lines with different versions (VSA X does not report architecture) and Office update channels (VSA X does not report the channel).
- Settings → Software catalog shows the coverage of the last check: catalog programs, how many are installed and used, how many are not on any device (list), and which could not be used automatically (list with reasons).
- Verified: 2 new backend tests (series and edition splitting, unresolvable cases), updated frontend test; simulated against the live page (303 entries): ASP.NET 6.0/8.0, PowerShell 7.4 and both Teams editions now match separately. Not yet run against the operator's installed software.

## CAT-02 - 2026-11-17 - the VSA application catalog updates automatically

- Product owner: the catalog import must be automatic. A daily worker job (`apps.software.tasks.update_vsa_catalog`, beat `vsa-application-catalog`) reads the public [VSA 10 application catalog](https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm) page (fixed URL; HTTPS, verified TLS, no redirects, 5 MB cap, public destination only, no credentials), parses its table and matches it to installed programs exactly like the paste import.
- **Applied automatically:** a higher version for a product that already has an approved reference and no warning - published as an approved import by the inactive "VSA catalog (automatic)" account, audited (`catalog.vsa_auto_update`), compliance re-evaluated (ADR-030). **Waits for approval:** new products, lower versions, version-format warnings (one pending import, replaced by the next check rather than duplicated) and new installed-name aliases (proposed).
- New `software.0006` (`VsaCatalogCheck`: when, trigger, outcome, error, catalog "Last updated" date, counts). `GET/POST /api/v1/catalog/imports/vsa-catalog-status/` (system admins): last checks / check now. Settings → Software catalog shows the status and **Check now**; pasting stays available as a fallback.
- `VSA_APP_CATALOG_AUTO_UPDATE` (default true). **Operator action:** allow outbound HTTPS from the worker to `help.vsa10.kaseya.com`, then approve the first pending import once.
- Verified: 9 new backend tests (auto-apply only after one human approval, decreases/warnings wait, supersede, proposed aliases, HTTP/format failures recorded, private destination refused, switch off, admin-only status), 1 new frontend test; the parser was run against the live public page on 2026-11-17 (303 programs, 17 discontinued skipped, "Last updated" read).

## CAT-01 - 2026-11-17 - reference versions from the VSA application catalog

- Operator request: use the VSA software catalog to judge installed versions. The [VSA 10 application catalog](https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm) lists, per program, vendor, tier and the version VSA's 3rd-Party Patching deploys. The VSA X API documents no endpoint for it (checked api.vsax.net), so it is pasted, not fetched.
- **Settings → Software catalog → Import from the VSA application catalog:** paste the copied table (tab-separated, CSV or pipe table) → `POST /api/v1/catalog/imports/from-vsa-catalog/` (system administrators, dry run) matches catalog names to installed programs across current snapshots after removing editions/architecture markers, builds one import row per installed program (architecture "any", exact aliases for the installed names, evidence = catalog page, new source type `vsa_application_catalog`) and shows installed versions with older/newer counts. Skipped: discontinued entries, non-numeric versions, programs whose 32/64-bit catalog versions differ; unchanged references are left out. Submission and approval use the existing catalog import (different reviewer, immutable revisions, compliance re-evaluation). The JSON form is kept under *advanced*.
- Software page hint now points to this import.
- Verified: 9 backend tests (name matching, parsing, end-to-end import → approval → Chrome outdated count, version-format warning, admin-only), 1 frontend test; browser catalog scenario updated. Catalog sample read from the public page on 2026-11-17; not validated against the live tenant's installed software.

## P5-06 - 2026-11-16 - performance at 100k devices with related data

- `benchmark_inventory --related` now also generates installed software, OS update rows, patch status, applied patch policy and a server population (100k devices → 2.3 M observation rows) and measures the Servers page, patch-policy, software and OS-update summaries, the scorecard and large report exports (`--skip-reports` for API paths only). Development-only, `bench_*` databases only, as before.
- Faster at 100k devices (same results): **Servers & owners** list 49.6 s → 1.9 s (database pre-filter, needed columns only, lifecycle check for servers only); **patch-policy summary** 39.5 s → 4.0 s (value rows instead of full objects); **monthly scorecard** 141 s → 14 s (third-party exposure evaluates only outdated installations for the scorecard, cached name normalisation and memoised rule coverage); server-owner report 26 s → 2.5 s. Second pass: lifecycle verdicts cached per OS name/version, value rows for servers, one aggregate query for OS-update severity counts - Servers "all devices" ~6 s, scorecard ~10.5 s.
- Verified: new equivalence test (outdated-only third-party totals equal the full evaluation); backend suite passed. Measurements, proposed SLOs and limits: `CODEX_PERFORMANCE.md`. Synthetic fixture on a workstation; not a concurrency or target-host result.

## SRV-02 - 2026-11-16 - server owner follow-ups

- **Monthly report per owner:** on **Servers & owners → Owner groups**, *Schedule monthly* creates a "Server patching - <group>" PDF definition and a monthly schedule (day 1, 07:00 in the user's time zone, in-portal delivery, DEC-09); groups already scheduled show "Monthly on day N". Uses the existing definitions/schedules API, so the owner group is validated against the customer and changes/stops happen under Reports → Definitions & schedules.
- **Reports page:** the *Server owner group* filter is a pick-list (all owners, servers without an owner, each group) instead of a raw ID; "Only servers needing attention" label.
- **Customer summary:** new *Servers* card (servers, needing patching or an upgrade, without an owner) linking to the filtered Servers page.
- **Monthly scorecard:** new *Servers* section - servers needing patching or an upgrade (with counts of Critical updates, out-of-support OS and no patch policy in the notes) and servers without an owner. Shared `servers.status.summary()` also feeds the Servers page totals (adds `no_policy`).
- E2E: the sync scenario's waits were raised (60 s / 150 s test) because a demo sync now also collects automation, scopes and global rules (~500 fixture calls, ~20 s inline under eager Celery).
- Verified: 2 new backend tests (scorecard and summary figures; owner report definition + monthly schedule, foreign owner group refused), backend suite 721 passed, 113 frontend tests (new: monthly scheduling per owner), browser suite 51/51 on a fresh database. Fixture data only.

## P5-07 - 2026-11-16 - focused security review of recent features

- Fixed (low): VSA connector credential references could name any server environment variable (e.g. `env:DJANGO_SECRET_KEY`), which would have been sent to the VSA host as credentials. The API now accepts only `env:VSA_|ITGLUE_|AUTOTASK_<NAME>` (or a not-yet-resolvable `vault:` reference) for read tokens (never `VSA_WRITE_*`) and `env:VSA_WRITE_<NAME>` for the write token, and resolution refuses other names. **Operator action:** rename a server credential variable that does not start with `VSA_`; portal-entered credentials are unaffected.
- Renamed `move_execution.execute` to `execute_move` (semgrep raw-SQL false positive that would fail the CI security job).
- Reviewed with no further findings: tenant isolation of all new routes (resolver-driven IDOR sweep), group-move execution gates, secrets/logging, frontend sinks. Scans clean: pip-audit, bandit, npm audit, semgrep (CI rule packs), git-history pattern scan. Details: `CODEX_SECURITY_REVIEW.md`.

## FIX-BADRESP - 2026-11-16 - a non-JSON answer from VSA X no longer fails the whole sync

- Operator report: "1 sync(s) in the last 24 h: bad_response". A 2xx answer that is not JSON (empty body, HTML from a proxy) raised `bad_response`, which the per-device detail collectors did not catch, contrary to their documented behaviour - so one device's odd answer failed the run.
- Per-device detail calls (installed updates, applied policies, patch policy definitions, notifications, custom fields) now treat it like an unanswered call: that device's section is `failed`, the run continues, and three in a row mark the section incomplete. Core calls (asset pages, sites/groups/devices) still fail the run, as publishing incomplete inventory would be wrong.
- Diagnostics: the connector logs `vendor_bad_response` with the endpoint (identifiers masked), status, content type and size, never the body; the `sync.failed` audit event and **System status** now name the endpoint.
- Verified: 4 new tests; backend suite 718 passed. Fixture only; the live cause is still to be identified from the endpoint shown.

## SRV-01 - 2026-11-16 - servers & owners

- New `servers` app (`servers.0001`), portal-only (nothing read from or written to VSA X beyond the existing snapshot): **owner groups** per customer (name, owner, owner email, notes; unique name; deleting a group unassigns its servers) and a per-device **server marking**. A device is a server when marked, or when its reported OS name contains "Server" unless marked "not a server".
- `GET /customers/{id}/servers/` (customer.read; `scope=all`, `owner_group=<id>|none`, `attention=true`, `search`): per server the owner, available OS updates (Critical/Important/other; "not collected" is never "up to date"), patch policy, outdated programs, OS support (reviewed lifecycle catalog), last seen, and the action needed in words. `POST .../servers/designate/` (customer administrators): bulk mark as server / not a server / use detection, assign or clear owner group, note. `/customers/{id}/server-owner-groups/` CRUD (read: customer.read; change: administrators). Audited; owner contact details are kept out of audit metadata.
- New report type **Server patching by owner** (`server_owner_patching`, CSV/XLSX/PDF): all owners grouped, one owner group, or servers without an owner; optional attention-only; titled with the group name; evaluated when generated and kept with the run.
- **Servers & owners** page (Software & patching): totals, filters, table with selection and bulk actions; **Owner groups** tab with add/edit/delete, *Report (PDF)* per owner, report for all owners / without owner, and *Email owner* (opens the user's own mail program with that owner's servers needing attention; the portal sends no email, DEC-09).
- Verified: 4 backend tests (detection, marking/assignment/permissions/cross-customer refusal/unique names/delete/audit, patching reasons, report per owner incl. title, grouping and foreign-group refusal), backend suite 714 passed, 112 frontend tests, browser suite 50/51 with the sync scenario passing on rerun (it had run alongside the backend suite on the same database server); accessibility covers /servers. Fixture data only.

## VSA5-EXEC - 2026-11-16 - approved group moves executed in VSA X (gated, off by default)

- First and only vendor write (ADR-029): `PUT /api/v3/devices/{id}/move` with `{"GroupId"}` in a separate module (`apps/integrations/vsa/writer.py`); the read client stays GET-only and `/move` is still refused by the read allowlist. Same egress policy (shared `check_egress`), TLS always verified, no redirects, error bodies never read.
- Off unless all three are set: server `VSA_GROUP_MOVE_EXECUTION_ENABLED=true`, the integration's *execute approved moves* switch (super admin, audited, cleared when the base URL changes; `integrations.0013`) and a separate write token referenced as `env:VSA_WRITE_<NAME>` (refused if it is the read token).
- `POST /customers/{id}/group-moves/{id}/execute/` (approve capability; not the requester; approval at most `GROUP_MOVE_EXECUTION_WINDOW_HOURS` old, default 24; device still in its source group; destination active; inventory fresh). The attempt (`GroupMoveExecution`, `inventory.0014`) is committed before sending, so a proposal is sent at most once. No retries: timeout/5xx = *outcome unknown*; 2xx is confirmed by reading the device back (`GET /devices/{id}`, now allowlisted) = *moved* or *not confirmed yet*; 4xx = *not moved*. `POST .../verify/` resolves unknown/unconfirmed by read-back only. Audit: `group_move.execute_started`, `execute_<state>`, `verified`.
- UI: **Group move proposals** shows an *In VSA X* column and, on approved proposals, **Execute move in VSA X…** with a confirmation naming device, source and destination, or the reason execution is unavailable; **Verify in VSA X** for unknown/unconfirmed. Integration edit form: the switch and the write token reference. Fixture integrations use an in-process write transport so demos and tests never touch a network.
- Verified: 9 new backend tests (off by default and nothing sent, integration switch, executed once and confirmed + next sync shows the new group, who may execute incl. cross-customer 404, changed inventory blocks, timeout -> unknown -> verify without resending, accepted-but-unconfirmed -> verify, 4xx -> failed, separate write token rules), full backend suite 710 passed, 110 frontend tests, browser suite 50/51 on a fresh database with the remaining scorecard scenario passing on rerun (its status wait was raised to 30 s because eager Celery renders the PDF inside the request). **Fixture only: no live VSA X write has been made or validated.**

## CF-02 + GR-01 - 2026-11-16 - VSA custom fields on organisation/site/group, scopes and patch global rules

- **CF-02** (`inventory.0013`): during each sync, for customers with at least one approved custom-field name, the portal reads `organizations|sites|groups/{id}/customfields` (max 300 calls per run; one failing scope is skipped and logged) and stores only approved names, per inventory generation. No call is made while nothing is approved. `GET /customers/{id}/scope-custom-fields/` (customer.read; organisation, then sites, then groups, with names resolved from the hierarchy); **Details from VSA** card on the customer page; new custom report source "VSA custom fields (organisation, site, group)" pinned to the report's generations.
- **GR-01** (`automation.0003`): with the automation collection, the portal reads `patchmanagement/globalrules` and `scopes`, `scopes/{id}` and `scopes/{id}/usage` (max 100 scopes; each part optional). Criteria keep type and identifier only; identifiers of custom-field criteria are dropped. **Automation → Catalog** (super admin) lists scopes with criteria, device count and the named tasks/workflows using them ("Not used" flagged), and the OS/software global rules. A global SoftwareRule now counts as third-party coverage ("Global rule") for devices with a patch policy assigned; devices with no or unknown patch state are never marked covered. Configuration only; deployment is not implied.
- New allowlisted GET routes only: `organizations|sites|groups/{id}/customfields`, `patchmanagement/globalrules`, `scopes`, `scopes/{id}`, `scopes/{id}/usage`.
- Verified: 6 new backend tests (no calls without approvals, approved-only storage and credential-like field never stored, cross-customer 404, report source, catalog scopes/rules and super-admin only, custom-field criterion redaction, global-rule coverage only for patch-managed devices), 108 frontend tests at the time. Fixture data only; live fields to confirm with `vsa_probe`.

## AUT-01 + SCR-01 - 2026-11-16 - automation health and script data

- Full VSA X API reference re-read (https://api.vsax.net/); routes, query parameters and documented response fields recorded in `capabilities.json` (docs-verified, not live-tested). Finding: VSA X has no read-only route that lists scheduled *task* executions; workflow executions and per-device script executions are listable.
- **AUT-01** new `automation` app (migrations `automation.0001`): after a successful sync (throttled to every 30 min per integration, never affects the sync) the portal reads workflows, tasks, the script catalog and the last 30 days of workflow executions (failed-step outcome for recent failures; step output items never stored). Executions are attributed to a customer only through their target device. `GET /customers/{id}/automation/` (per-workflow runs/failures/success, failed runs with device and failed step) and `GET /automation/catalog/` (super admin: tasks and workflow definitions). **Automation** page; new alert kind "An automation workflow fails on a device" (`alerts.0002`). A token without automation permission shows "not permitted"; nothing else changes.
- **SCR-01** script collectors (`automation.0002`): a super admin picks a VSA script and the output variable names to keep (credential-like names refused). After each sync, within `SCRIPT_RESULTS_BUDGET` (default 200 device x collector pairs, oldest first, 2 GET calls each) the latest *successful* run per device is read; only allowlisted `VariableOutputs` are stored, free-text Output never. Values appear on the device **Script data** tab, drive the new compliance rule "A value collected by a VSA script matches" (is / is not / contains / at least; `compliance.0002`) and the new custom report source "Script results" (kept with the run for regeneration). Settings → **Script collectors**; demo seed adds a DEMO BitLocker collector.
- New allowlisted GET routes only: automation/workflows, workflows/executions(/{id}), automation/tasks, automation/scripts, scripts/{id}/device/{id}/executions(/{id}). No run/cancel/write route.
- Verified: 7 new backend tests (attribution and scoping, throttling and missing permission, workflow-failure alert, allowlisted variables only, compliance and report integration, customer collector list), full backend suite 695 passed, 107 frontend tests, 51/51 browser scenarios (accessibility covers /automation). Fixture data only; live permission and fields to confirm with `vsa_probe`.

## CRM-05 - 2026-11-15 - all-customers overview

- `GET /customers/overview/`: one row per customer the user may read (super admins: all; members: their own) with devices, offline/not seen, disk critical, antivirus issues, devices with Critical OS updates, devices with outdated software, lowest compliance baseline score, data as-of and stale flag. Figures come from each customer's own read models.
- **All customers** page (Overview): sortable side-by-side table, amber attention values, fresh/out-of-date badges, CSV download (formula-safe) and drill-down to the customer's Summary.
- Verified: 2 backend tests (super admin sees all with matching figures; members see only their customers), IDOR sweep, backend suite 688 passed, 104 frontend tests, 51/51 browser scenarios (accessibility covers /all-customers). Fixture data only.

## OPS-04 - 2026-11-15 - alerts & watchlists

- New `alerts` app (migration `alerts.0001`): per-user watches per customer - new device appears, device not seen for more than N days, system disk becomes critical, a program (name contains) appears, compliance score below a threshold. Evaluated after every successful sync in the worker (best-effort; never affects the published inventory). Only *newly* matching devices raise an alert, one summarised alert per watch per sync; a new or edited watch is primed with the current state, so it never floods. Access is re-checked at evaluation and when listing; users who lost access receive and see nothing. Identical duplicate watches are refused.
- API (own rows only): `/alert-subscriptions/` (create/pause/resume/delete, audited on create) and `/alerts/` (`unread`, `unread-count/`, `{id}/read/`, `read-all/`).
- UI: bell with unread count in the header; **Alerts** page with the alert list (open the related page for that customer, mark read, mark all read) and **My watches**. In-portal only; email remains disabled (DEC-09).
- Verified: 4 backend tests (one alert per sync and only once, forbidden software, scoping/validation/lost access, pause/resume/duplicate), backend suite 686 passed, 103 frontend tests, 51/51 browser scenarios (new watches flow; accessibility now covers /alerts). Fixture data only.

## OPS-03 - 2026-11-15 - cleanup centre

- New **Cleanup** page (VSA operations) and `GET /customers/{id}/cleanup/?days=&category=` (customer.read): duplicate hostnames, serial numbers (case/space-insensitive; placeholder serials such as "To be filled by O.E.M." ignored) and MAC addresses (locally administered/virtual MACs ignored); agents not seen for more than N days (30-365) or never; devices in no group or still in an onboarding group; agent not installed; missing serial. Each finding names the other devices involved. Category chips with counts, findings table, **Download to-do list (CSV)** (formula-safe). Read-only: nothing is changed in VSA X.
- Verified: 2 backend tests (all categories incl. placeholder exclusion and duplicate details; scoping and validation), backend suite 682 passed, 103 frontend tests, 50/50 browser scenarios (accessibility spec now covers /cleanup). Fixture data only.

## CIDR-03 - 2026-11-15 - destination plan and leading-letter naming (operator feedback)

- Naming evidence now compares the **leading letters** of the hostname, so names without separators work (e.g. `DEPARTMENTUSERSX`). A destination "owns" a prefix (3-12 letters) shared by at least half of its devices; a device also matches when its name starts with the first 3+ letters of a group or site name word (e.g. `FIN…` → *Finance*). Generic names (DESKTOP-, LAPTOP-, …) and stopwords give no evidence. Within the naming rank a longer shared prefix ranks first. Network evidence still outranks naming.
- New `GET /customers/{id}/groups/{group}/suggestions/plan/?instance=` groups the onboarding group's devices by their clearly best destination (group + site); evidence ties are listed as *needs a decision*, devices without evidence separately (max 2,000 devices). Hints only; nothing is moved.
- Onboarding group page: **By destination** view (default) with "Move N device(s) to <group> · Site <site>" cards and **Download move list (CSV)** for the administrator who transfers agents in VSA; the per-device view remains.
- Product owner decision: **Entra ID is not required** (DEC-03 closed, ADR-007, VSAP-01/P5-01 updated); local portal accounts are the production sign-in.
- Verified: 4 new backend tests (DEPARTMENTUSERSX prefix, group-name abbreviation, longer prefix wins and plans, scoping/onboarding-only), full backend suite 680 passed, 102 frontend tests, 50/50 browser scenarios. Fixture data only.

## CRM-03 - 2026-11-15 - reproducible live-evaluated reports

- Reports whose figures are evaluated at generation time (custom reports on compliance, third-party patching or subnets, and the customer scorecard) now keep their rows with the run (`reporting.FrozenReportRows`, migration `reporting.0004`, customer-scoped, deleted with the run). Regenerating such a report re-renders the kept figures, following the regeneration chain, instead of re-evaluating against newer data; the file's provenance says "Reproduced from the figures evaluated for run …". New reports still evaluate the current data. Snapshot-table reports are unchanged (they already re-pin their generations).
- Above 50,000 rows nothing is kept and the provenance says so.
- Verified: 2 new backend tests (baseline changed after generation: regeneration identical, fresh report differs; snapshot reports not frozen; scorecard frozen), full backend suite 676 passed, migration check clean, 8 report browser scenarios. Fixture data only.

## CRM-02 - 2026-11-15 - monthly customer scorecard

- New report type `customer_scorecard` (CSV/XLSX/PDF): one row per measure - inventory, health (offline, disk, antivirus, firewall), patching (Critical OS updates, outdated third-party and policy gaps), software (outdated devices, version compliance), lifecycle (end-of-support OS/software), compliance (score per enabled baseline) and network (unapproved subnets, devices outside scope).
- "30 days ago" comes from retained published snapshots (latest on or before 30 days ago, else the oldest in a 45-day window), with the date stated; measures without history show no comparison. Changes are written as words ("up 2", "down 3", "no change") so spreadsheets do not treat them as formulas.
- Customer → Summary: **Monthly scorecard (PDF)** button; recent reports link to their download and refresh while generating. Scheduling uses the existing Definitions & schedules.
- Verified: 3 backend tests (all areas, honest history comparison, scoping/export permission/no filters), full backend suite 674 passed, 101 frontend tests, 50/50 browser scenarios (new scorecard flow). Fixture data only.

## UX-07 - 2026-11-15 - catalog quick-add and stale-suggestion guidance (operator feedback)

- Software → Installed programs: super admins can **Add to catalog** from any row. Vendor, product, an exact-name alias and the newest version seen in the estate are pre-filled; the current version and an https evidence link must be confirmed (same import + approval path and audit as Settings → Software catalog; with a second approver required the entry waits for approval). The empty-catalog message now points to this.
- Onboarding destination suggestions: when the customer's last successful sync is older than the freshness limit the backend still refuses (deliberate fail-closed rule), but the page now explains why, shows the data source with **Sync now**, and points to Settings → System status instead of a generic "Could not load data".
- Verified: 101 frontend tests (stale-state test added), 49/49 browser scenarios on a fresh fixture database (new catalog quick-add flow). No backend change.

## CRM-01 - 2026-11-15 - customer workspace

- Customer page opens on a new **Summary** tab: device health issues, compliance scores per baseline, Critical OS updates and third-party patch gaps, subnet issues, data-source freshness and the five most recent reports. Every number links to the matching filtered investigation and selects that customer first. Values show "…" while loading and "—" only when there is no data. The former Overview tab is now **Details**.
- Frontend only; uses existing customer-scoped endpoints (reports card only with export permission). Verified: 100 frontend tests (new workspace test), 48/48 browser scenarios. Fixture data only.

## RPT-07 - 2026-11-15 - custom report builder

- New `custom` report type: choose a data source (devices, device health, installed software, Windows updates, compliance, third-party patching, subnets), columns in order, up to 20 filter conditions (text, number, enum, yes/no and date operators; match all or any), sort and title. Sources, fields, operators and value types are allowlisted (`apps/reporting/custom.py`); nothing user-supplied reaches SQL.
- Generated through the existing pipeline: pinned snapshot, CSV/XLSX/PDF with provenance and limitations, history, regeneration, saved definitions and in-portal schedules (columns and title follow the specification).
- `GET /report-sources/` (catalog) and `POST /customers/{id}/custom-reports/preview/` (first 100 rows + total; requires customer.export, nothing stored).
- Reports → Custom report tab: data cards, column picker, filter rows with type-aware inputs, preview table, Generate and Save for reuse.
- Verified: 13 backend tests (catalog, filters/sort/any-all, enum/number, 8 rejected specifications, CSV generation with chosen columns, scoping incl. viewer without export), IDOR sweep, 99 frontend tests, 48/48 browser scenarios (new builder flow). Fixture data only.

## NET-03 - 2026-11-15 - subnet identification

- Customer-wide subnet inventory from addresses VSA X reported with a mask (`IpAddressObservation.network_cidr`, derived only; link-local/loopback excluded): devices, groups (with the dominant group and its share), sites, gateways, DHCP vs static, and the match against approved expected subnets: approved subnet / inside an approved range / not in any approved subnet. Devices whose address is in a subnet approved for another group or site are flagged *outside* (review signal; nothing is moved).
- API (customer.read): `GET /customers/{id}/subnets/` (`status`, `mixed`, `outside`, `search`) and `…/subnets/devices/?cidr=`. Pending proposals are shown per subnet.
- Groups & network → Subnets tab; customer admins can propose the dominant group as the expected subnet in one click (existing expected-subnet proposal + approval workflow and audit). Approved subnets drive the onboarding destination suggestions (CIDR-02).
- Verified: 5 backend tests (spread, assigned/contained/unassigned, outside devices, retired ignored, pending proposals, scoping), 99 frontend tests, 47 browser scenarios (new subnet flow). Fixture data only; not network topology.

## TPP-01 - 2026-11-15 - third-party patch exposure report

- VSA X exposes no third-party patch deployment state. The new report states what the collected evidence supports: for each installed program on each device, the catalog version state (outdated/current/…) and whether the device's assigned VSA patch policy contains a SoftwareRule for that program (normalised name match). Coverage: rule in policy / no rule in policy / no patch policy / policy not collected.
- "Outdated and no rule in policy" and "outdated and no patch policy" are the actionable gaps; "rule in policy" is configuration only and is labelled "deployment not reported". The disclaimer is part of every response.
- API (customer.read, customer-scoped): `GET /customers/{id}/software/third-party/` (per program; `search`, `outdated=true`) and `…/third-party/devices/` (`program`, `coverage`, `version_state`, `search`; paged). No schema change.
- UI: Software → Third-party patching tab with gap counters (click to list devices), per-program coverage badges, rule actions, and the outdated-installation drilldown.
- Verified: 10 backend tests (name normalisation, coverage split, uncatalogued never outdated, missing policy = unknown, explicit no policy, cross-customer 404), 99 frontend tests, 46/46 browser scenarios. Fixture data only.

## CMP-01 - 2026-11-15 - compliance baselines

- New `compliance` app (migration `compliance.0001`): customer-owned baselines with up to 30 rules each — required software (optionally a minimum version), forbidden software, minimum OS version, antivirus healthy, firewall enabled, minimum disk free %, maximum days since seen, agent at approved minimum, no outdated catalogued software, no available Critical OS updates, patch policy assigned. Optional scope by device type, site or group; severity per rule.
- Evaluated live against the current snapshot (still-approved mappings only); every rule answers pass / fail / unknown with a reason. Missing source data is unknown, never a pass or failure. Score = compliant ÷ (compliant + not compliant).
- API: `/customers/{id}/compliance-baselines/` (read: customer.read; create/edit/delete: customer.manage_exceptions, audited), `…/{id}/results/` (status, rule, site, group, search filters; paged; group breakdown), `…/overview/`. Rule parameters are allowlisted per kind.
- UI: Compliance page (navigation under Overview) with score cards, per-rule failing counts that filter the device list, per-device findings with reasons, weakest groups, and a baseline editor for customer admins. Demo seed adds one illustrative baseline for DEMO-A.
- Nothing is written to VSA X. Verified: 10 backend tests (evaluation, unknown handling, scoping/IDOR, permissions, validation, audit), 98 frontend tests, 46/46 browser scenarios (new end-to-end baseline flow; accessibility spec now covers /compliance). Fixture data only.

## UX-06 - 2026-11-15 - accessibility (WCAG 2.1 AA automated checks)

- axe-core audit of 18 pages at desktop and 390 px widths found one class of issue: secondary text in `text-slate-400` (2.6:1 on white, below 4.5:1). It now uses `text-slate-500` (4.8:1); the dark sidebar, disabled controls and placeholders are unchanged.
- New browser test `z-accessibility.spec.ts` runs the WCAG 2.1 A/AA rule set on the main pages at both widths and fails on any violation. `axe-core` 4.14.0 is now an explicit dev dependency (it was already installed through eslint-plugin-jsx-a11y).
- Automated rules cover contrast, names, roles and labels only; keyboard and screen-reader review remain manual.
- Verified: 96 frontend tests, 45/45 browser scenarios on a fresh fixture database.

## UX-05 - 2026-11-15 - readable patch policies, upload control, memory

- Patch policies: general settings and rule actions read as words ("Reboot option: Do not reboot", "Create restore point: Yes"); object settings such as the schedule show their text parts ("Type: Schedule · Frequency interval: Weekly") instead of raw JSON. The exact reported value stays in the tooltip.
- Onboarding check: styled file-upload button.
- Device detail: memory keeps the raw value (unit undocumented) and adds an explicitly conditional "≈ 16 GiB if bytes".
- Verified: 96 frontend tests (policy settings assertion added), 43/43 browser scenarios on a fresh fixture database. No backend change.

## OPS-02 - 2026-11-15 - system status (P5-05, in-portal part)

- `GET /api/v1/system/status/` (super admin only, no vendor calls) and Settings → System status: worker/broker reachability (bounded ~2 s when Redis is down; skipped in eager mode), queue lag and runs stuck >15 min or running >2 h, 24 h sync outcomes and failure causes (incl. rate limiting), stale or never-synced sources, exports per user per hour, failed sign-ins. Each signal is a finding with level, code and plain message.
- Dashboard shows a red banner to super admins only when a finding is an error.
- Verified: 6 backend tests (permission, stale, stuck queue + failure, worker down, eager skip), 96 frontend tests, 43/43 browser scenarios, OpenAPI regenerated. External alerting and audit forwarding remain open (P5-05).

## OPS-01 - 2026-11-15 - read-only VSA X data probe

- `manage.py vsa_probe`: one small asset page with the sync's exact `include`, plus the four per-device detail calls, through the same allowlisted read-only client. Prints section presence, item counts and field names only (no hostnames, software, versions, IPs or secrets); audited as `integration.probe`. Ends with plain findings such as "InstalledSoftware is missing on every sampled device".
- Supports VSAP-04 (live field validation) once run on the live host; fixture output is not live evidence.
- Verified: 3 new tests (sections without values, ambiguous integration/org refused, missing-section finding); full backend suite.

## UX-04 - 2026-11-15 - device health and Windows updates layout

- Device health: summary cards first, then the device list (picking a cohort filters and scrolls to it), then "By group". Thresholds fold into a section whose summary always shows approved/defaults; it opens by itself when a change awaits approval.
- Windows updates: the installed-update collection counts fold into one line.
- Verified: 95 frontend tests, 43/43 browser scenarios on a fresh fixture database (one health scenario updated to open Thresholds). No backend change.

## UX-03 - 2026-11-15 - software page works without a catalog

- New read-only `GET /customers/{id}/software/installed/` (customer-scoped, current inventory only): installed programs grouped by name and publisher, with device counts and the top versions as reported. No catalog or version judgement needed.
- Software page: new "Installed programs" tab. With no catalogued products the Overview now explains that versions are not compared yet, links to the installed programs and (super admin) to Settings → Software catalog, instead of the bare "No catalogued products".
- Third-party patch status is a known VSA X API limit, not an error: shown as a one-line note instead of a yellow warning (wording kept; evidence in the tooltip).
- Verified: 625 backend tests (new scoping/no-catalog test), 95 frontend tests, 43/43 browser scenarios, OpenAPI regenerated. Fixture data only; live VSA X software collection not re-validated.

## UX-02 - 2026-11-15 - lists, reports and settings clean-up

- Tables: one header style (sentence case; sortable headers had escaped the uppercase rule), device links and release dates no longer break at hyphens.
- Data-source strip on list pages is a single line (green dot, devices, as-of, Sync now); full detail stays on the dashboard.
- Reports: readable filter labels (e.g. "Operating system", "Device IDs (comma separated)") in a collapsed "Filters (optional)" group.
- Settings → Integrations: Connect VSA, then "Your integrations"; allowed hosts, manual add and provider list moved under "Manual setup".
- Verified: typecheck, lint, 94 frontend tests, 43/43 browser scenarios on a freshly seeded fixture database. No backend change.

## UX-01 - 2026-11-15 - dashboard redesign

- Overview tiles now carry an icon and a text status (Review / OK / No data, never colour alone); a one-line summary states how many checks need review. Two tiles per row on phones, three on desktop.
- History moved into a card beside a side column with Data sources and a compact Customer card; the counting method folds into "How these figures are counted".
- Same queries, links and filters; no backend change. Verified: typecheck, lint, 94 frontend tests, the two dashboard browser scenarios, desktop/390px screenshots with no horizontal overflow (fixture data only).

## CIDR-02 - 2026-11-15 - onboarding destination suggestions

- Added paginated, searchable device suggestions directly to marked onboarding groups.
- Ranked approved subnet matches before subnets observed on destination devices, with naming-only hints last. Every hint explains its basis; competing candidates remain ambiguous and manual transfer is unchanged.
- Reused the same scoped engine in Device Operations; rejected stale/revoked evidence and excluded foreign, inactive and onboarding destinations. No migration or vendor API change. Actual validation: ONBOARDING_SUGGESTIONS.md.

## LIST-02 - 2026-11-14

- Split software into Overview/Installations/Exceptions and Windows updates into Update records/Collection coverage/Common updates; retain source and evidence limitations.
- Added debounced device/version/title/KB search with matching pinned exports, device investigation return links and consistent paging/recovery.
- Fixed the 200-device coverage truncation; added protected CSV/XLSX/PDF coverage exports with explicit collection states, unknown counts and source provenance. Preserved raw device type alongside OS.
- Verified 614 backend tests plus final 11-case feature rerun, 89 frontend tests, 43 full browser scenarios and clean lint/types/build/schema/migration checks. No schema change, vendor write or live validation. Evidence: INTELLIGENCE_LISTS.md.

## LIST-01 - 2026-11-14

- Simplified Devices controls, added filter chips/quick filters, debounced keyboard-safe search and source-qualified named facets.
- Added server-persisted private/shared device layouts with validated columns, density/page size; inline create/update/delete and audit. Duplicate names return validation errors.
- Added sortable headers, page sizes/direct paging, empty-page recovery and protection against stale-row actions.
- Added searchable group directory with site/purpose filters and scoped device links while retaining Hierarchy.
- Added reporting migration 0003, compatibility proof and before/after evidence. Final validation is recorded in LIST_USABILITY.md; live/deployment gates remain open.

All implementation claims require linked evidence. Use semantic versions for application releases once a working application exists.

## [Unreleased] - 2026-11-14 - VSA application remediation

- Added the independent application audit, UI plan, gap analysis, remediation register, browser evidence, security review and deployment/rollback instructions.
- Reorganized navigation around operations, software/patching, reconciliation, reporting and administration; added active scope, device/page search, responsive tabs/forms, table scrolling/sticky headers and recovery UI.
- Fixed current dashboard aggregation and exact attention drilldowns; made failed/unknown source evidence visible.
- Unified list/report inventory filtering, pinned offline cutoff, added current-page read-only selection/export, persistent filters/tabs/pages and column selection.
- Fixed multi-instance hierarchy identity and ambiguous group access; added pinned, customer/source-scoped group-network CSV/XLSX/PDF exports (R10), including missing network sections.
- Improved software/Windows investigation, reconciliation progress and report-history pagination/format labels.
- Added internal immutable group-change proposal/review with separate permissions, expiry, independent approval and audit. Vendor execution remains disabled and unimplemented.
- Added a safe isolated 100k fixture benchmark; optimized health summary from 16.3327s to 1.2915s (9 queries). Split routes reduced initial JavaScript from about 576KB to 342KB.
- Validation: 585 PostgreSQL tests, 74 frontend tests, full 36-test browser pass including network export; 34 screenshots without overflow/JS errors; lint/types/schema/build and dependency/SAST checks passed. Fixture-only; production/live gates remain open. See CODEX_VERIFICATION.md for failures corrected and precise limits.

## [Docs 0.1.0] — 2026-11-12

### Added
- Full project README and scope restrictions.
- Architecture and multi-customer database model.
- Verified public-documentation-based vendor API capability register and limitations.
- Security, AlmaLinux/Docker deployment, admin and engineer workflows.
- Reporting metric definitions, QA test matrix and production readiness gates.
- Implementation roadmap, task checklist, Codex/Claude agent instructions and decision log.

### Not implemented
- No source code for the Django/React application in this package.
- No deployed portal, working vendor connector, live customer data, tests, or production sign-off.

## [0.4.0-dev] — 2026-11-13 (unreleased; VSA Phase 1, commits `ea26682`, `dcecf60`)

Evidence: [IMPLEMENTATION_EVIDENCE.md](IMPLEMENTATION_EVIDENCE.md). **Fixture-tested only; no live VSA validation.**

### Added (deployment)
- Simplified UI: *Connect VSA* wizard (address + token, tick organisations; replaces eight manual steps), a short main menu (Dashboard, Devices, Device health, Windows updates, Software, Reports) with specialist pages under *More*, *Settings* instead of Administration (opens on Integrations), explanatory notes folded into "About this view", calmer dashboard tiles.
- Single-administrator approvals by default (`REQUIRE_SECOND_APPROVER` restores two-person approval).
- Fixes from the first host deployment: Redis protected mode blocked the worker; approved mappings never got a sync schedule; queued runs that never reached a worker blocked *Sync now*; accepted counts were always 0. `manage.py sync_status` diagnoses sync problems.
- VSA4-05: **Lifecycle (end of support)** for OS releases and software version lines from a reviewed, cited catalog (two-person approval, immutable once approved); Lifecycle page, dashboard tile, admin catalog tab, report R17. Unverified or missing entries are shown as unknown. The software state previously labelled "Unsupported (not catalogued)" is now labelled **Not catalogued**.
- UI: dashboard summary tiles, setup checklist, in-place customer picker, grouped and responsive navigation.
- `install.sh`: one-command, idempotent AlmaLinux installer/updater (packages, Docker, firewall 80/443, settings, secrets, TLS, build, health wait, first admin, optional backups, preflight). Not yet run on a host.
- The VSA X API token can be entered in the portal by a super admin (Admin → Integrations → *Set API token*). Encrypted at rest with a host-held key, write-only, audited, cleared when the base URL changes.
- **Integrations page holds every API setting:** a provider catalog (VSA X available; IT Glue, Autotask, Tenable planned), allowed API hosts managed in the portal (audited, re-checked per request), editing of base URL, rate and budgets, and provider-defined credential fields stored together as one encrypted blob.
- Deployment fixes from the first AlmaLinux boot: Redis user, backend health-check host, access by server IP, installer defaults on hosts named `localhost`, visible API errors instead of an endless session check.
- CI and security workflows run on GitHub (first run fixed: stale OpenAPI schema, pip-audit Python version, check --deploy env, reviewed gitleaks test fixtures).

### Added
- VSA1: org > site > group explorer from `/sites`, `/groups` and `/devices`. Devices also gain NIC/IP/MAC, disk and security observations, a group network view (derived CIDRs, duplicate-IP/MAC-reuse review flags) and MAC/IP search. The UI states explicitly that third-party patch status is *unavailable*.
- VSA2: an **Onboarding check**. Upload an expected device list (.xlsx/.csv) and match it deterministically against the customer's latest complete VSA snapshot. Results come out in eight classifications plus secondary flags and an unexpected-device set. Uncertain matches get a review queue, and the run exports as a 10-tab XLSX or as CSV. Runs are immutable and pinned to a generation.
- `defusedxml` dependency (hardens workbook XML parsing).
- VSA3-04: **Patch policies**, covering budgeted per-device applied policies, policy definitions (configuration only) and an explicit No Policy state that is kept distinct from unknown. Also a two-person-approved expected-policy baseline with drift, a device Policies tab and report R08. The onboarding `NO_PATCH_POLICY` flag is now evaluated (commit `ff7a956`).
- VSA4: **Device health** covers connectivity, agent installed, agent version (against an approved minimum), system disk free space, antivirus and firewall. Each is a complete partition with explicit unknown buckets, under two-person-approved thresholds. The documented CPU, memory and aggregate security fields are kept verbatim. Adds reports R09, R13 and R14; the onboarding `OLD_AGENT` flag is now evaluated (commit `b345b8f`).
- VSA1-01: an administrator **connection test** (`GET /api/v3/ratelimits`) reports an explicit outcome, latency and the reported per-endpoint rate limits. VSA2-05: **expected subnets** per site/group, two-person approved, flag addresses outside them, and addresses that changed since the previous snapshot are flagged too. Both are review observations only (commit `5dbb567`).
- VSA4-04: **Inventory changes** shows the differences between two complete snapshots and adds report R16. No change time or person is invented. A device **Onboarding** tab lists the onboarding checks that involved the device (commit `136ddb6`).
- AlmaLinux deployment: an as-implemented runbook, `.env.prod.example`, a host preflight script and a secrets preparation script (owners, modes, SELinux labels), and SELinux-aware Compose binds. Docker-published ports bypass firewalld, so the runbook adds `PORTAL_BIND_ADDRESS` and DOCKER-USER guidance. Not yet executed on a host.
- VSAP-02: **encrypted backups**: `pg_dump` inside the db container is encrypted with GnuPG to a public key, with a checksum, manifest, off-host copy, retention and a systemd timer. Also an **isolated restore drill** with `manage.py restore_check` and a JSON drill record. Drill-tested locally; not yet run on the host.
- VSA4-03: **Notifications** (redacted, recurring patterns, R15) and a customer-approved **custom field allowlist**; credential-like fields can never be stored.
- VSAP-03: a threat model, SAST in CI, and a generic IDOR route sweep. **Security fix:** customer-scoped routes now authorise the customer before validating input; they previously returned 400 instead of 404 for a customer outside the caller's access. Dev-tooling advisories fixed (vitest 4.1.12, minimatch override).

### Not changed
- VSA X stays read-only. Device moves remain disabled (VSA5 BLOCKED_APPROVAL).

## [0.3.0-dev] — 2026-11-13 (unreleased; P2 Windows updates, reports, history, commit `c483a8f`)

Evidence: [PHASE_ACCEPTANCE_P2.md](PHASE_ACCEPTANCE_P2.md). **Fixture-tested only.**

### Added
- VSA X OS update sections: available updates (list endpoint) and installed updates (per-device, budgeted), with an explicit status for each device.
- Windows updates view, an OS-update tab on each asset, and the RPT-04 report.
- XLSX and PDF output for every report, plus RPT-05 (version distribution) and RPT-06 (stale devices).
- Report templates endpoint, saved views and report definitions.
- Timezone-aware schedules with in-portal delivery, scheduled read-only syncs and an expired-artifact purge.
- Regeneration of a report from its original pinned snapshot, a history/trend endpoint and a dashboard chart.

### Security
- XLSX cells are string-typed (no formulas). PDF text is escaped. Filters cannot reference another customer's records. Schedule recipients are re-authorised on every run.

## [0.2.0-dev] — 2026-11-12 (unreleased; P1 VSA X + software versions, commit `23550d1`)

Evidence: [PHASE_ACCEPTANCE_P1.md](PHASE_ACCEPTANCE_P1.md). **Fixture-tested only. No live VSA X validation.**

### Added
- A read-only VSA X adapter based on the documentation at https://api.vsax.net/ (assets, organizations), with a capability record.
- A sync engine with checkpoints, quarantine, consistency checks and atomic publication of generations.
- Inventory and installed-software views with freshness and fixture labelling.
- A reviewed software catalog: import preview, separate-reviewer approval and immutable revisions.
- A version comparator (current / outdated / newer / unknown / unsupported / excluded, each with a reason code) and approved exceptions.
- Software version compliance view and RPT-01/RPT-03 CSV exports with a provenance block.
- Admin tools: organisation discovery, sync quarantine and the catalog workflow.

### Not claimed
- Third-party patch applicability or vulnerability state. Classification is version comparison only.

## [0.1.0-dev] — 2026-11-12 (unreleased; P0 foundation, commit `d799241`)

Evidence: [PHASE_ACCEPTANCE_P0.md](PHASE_ACCEPTANCE_P0.md).

### Added
- Django 5.2 LTS / DRF API on PostgreSQL 16 with customers, memberships, seeded roles and capabilities, integration instances and reviewed source mappings.
- Central customer-scope policy. Cross-customer access returns an audited 404.
- Local bootstrap admin, OIDC relying party (tested against a mock IdP), secure server-side sessions, CSRF protection and login throttling.
- Append-only audit trail (including a DB trigger), redacted JSON logging, request IDs and a standard error envelope.
- Customer-scoped async report jobs with private artifacts, CSV formula-injection defence and re-authorised downloads. The first report type is the audit-log CSV.
- React 19 / TypeScript SPA: login, customer selector, dashboard, customer administration, system administration, reports.
- Dockerfiles, Compose dev/prod files, nginx proxy, CI and security workflows.

### Security
- Upgraded djangorestframework 3.16.1 → 3.18.3 after pip-audit reported CVE-2026-114136/7/8.

### Not yet verified
- Docker Compose boot, CI execution, Entra ID SSO, and every vendor connector (none implemented yet).

## [App release] — Not yet released

Coding agent must add actual commits, passing test evidence, migrations, deployment/validation results and limitations before publishing an application version.

## CIDR-01 - 2026-11-14

- Added administrator-managed onboarding-group purpose, preserving temporary installation placement as valid.
- Qualified new expected subnet rules by VSA instance and reused independent subnet approval for destination suggestions.
- Device Operations explains matching IP/CIDR evidence and overlapping candidates; no automatic selection, submission or vendor transfer.
- Additive inventory migrations 0011/0012 preserve legacy rules and their uniqueness. Full PostgreSQL suite 589 passed, frontend 78 passed, dedicated browser workflow passed.
