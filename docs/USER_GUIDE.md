# Engineer and viewer user guide

## Verified VSA workflows — 2026-11-14

These paths were exercised with synthetic fixtures; live source accuracy remains a separate pilot gate.

1. Select an authorized customer in the header. The scope strip identifies the customer for every view. Navigation is grouped by workflow, and **Find a page** narrows navigation links. Header device search applies only to the selected customer.
2. Select a dashboard metric to open its exact investigation: offline/stale/never-seen health, critical disk, antivirus issues, critical available OS updates or outdated software versions. Source freshness/failures are visible on the dashboard.
3. In **Devices**, use search, group/site/type/OS/online filters and sorting. The URL retains the view and page. **Columns** controls visible columns. Check rows for read-only reporting, then **Export selected devices**; selection is limited to the displayed page and resets when its page/filter view changes. Regular **Export inventory** exports the filtered population, not just one page.
4. Open a device to investigate its grouped overview and existing software, updates, policies, network, hardware/security, notifications, onboarding and history tabs. Tabs survive reload. **Back to devices** restores the originating filtered inventory URL. Wide tables and tab bars scroll within their containers; table headers stay visible.
5. **Software** classifications compare installed/reference versions; they are not pending patch claims. Device links open the investigation workspace. **Windows updates** separates available/installed rows, source severity and uncollected/unsupported populations. Filters and pagination stay in the URL.
6. **Onboarding check** uploads only after a customer is selected. Its progress indicator guides upload, mapping/preview, comparison and review/export. A new preview must finish validating before comparison can start. Ambiguous identities remain review items; no automatic move or merge occurs.
7. **Groups & network** separates source instances even when IDs match. Open a group to inspect reported adapters/addresses and use **Export group network** for CSV/XLSX/PDF. The file pins the source snapshot and retains missing-data states. Derived CIDRs are inventory observations, not physical topology.
8. **Reports** starts with inventory and supports format choice, saved definitions, schedules and paginated history. Downloads show the actual file format and remain protected by current customer permissions.
9. In a current device's **Operations** tab, an engineer with proposal permission can select an active destination in the same source/customer/organization and provide a reason. A different authorized administrator reviews it under **Group move approvals**. Requests expire after 24 hours and cannot be approved against changed or stale inventory. **Approval never executes a VSA change by itself.** Where an administrator has enabled execution (see *Executing an approved group move*), an approved proposal can then be executed in VSA X as a separate step.

Final screens and checks: [CODEX_VERIFICATION.md](CODEX_VERIFICATION.md). Existing design targets below may include future capabilities; the remediation backlog explicitly records remaining refinements and gates.

**Purpose:** Help internal authorized users interpret reports correctly. **Status:** Planned UI workflows, not existing screenshots or deployed instructions.

## 1. Signing in and selecting a customer

Access the Odyssey internal portal using the approved HTTPS URL. Sign in with organizational SSO/MFA when configured. Choose a customer from the selector; only assigned customers should appear. A global aggregated view is available only to explicitly authorized global roles. Always confirm the selected customer before exporting.

**The menu.** *Daily work* (Dashboard, Devices, Device health, Reports) and *Changes in VSA X* (Custom fields, Group
move approvals) are always shown. *Patching & software*, *Inventory & network* and *Administration* are folded; click a
group to open it (the portal remembers your choice), the group of the page you are on opens by itself, and **Find a
page** at the top of the menu searches every page.

## 2. Dashboard

With no customer selected, the dashboard shows totals (customers, devices, customers needing attention, customers with
out-of-date data) and lists **Your customers** with their key measures; amber figures need attention. Click a customer
to open its dashboard.

With a customer selected, the dashboard reads top to bottom:

1. **Header**: the customer, your role, **Customer details** and **Monthly scorecard (PDF)**.
2. **Data freshness**: one line when the data is up to date; the full sources panel (with the reason) when a sync
   failed, paused or the data is out of date. **Sync now** is here.
3. **Six figures**: devices, offline/stale, disk critical, antivirus issues, critical updates, outdated software. "!"
   means review, "✓" means fine; the bar shows the share of devices. Click a figure to open the filtered list.
4. **Patching, Compliance, Servers, Network**: each number links to its list; **Open →** opens the page.
5. **History** and **Recent reports**. History draws lines from the second day of data.

The customer's **Summary** tab (Administration → Customers) shows the same blocks plus **Details from VSA**.

The dashboard summarizes device inventory, installed software, version-compliance classifications, OS update availability and integration health. Each card links to a filtered list. Every metric must display the **data-as-of** timestamp and warn if the source is stale or incomplete. **Unknown** means no justified classification, not automatically compliant.

## 3. Find a workstation or server

**Fastest:** type part of the name, the serial number or the VSA device ID into **Find a device** in the header. Matches
from every customer you may read appear as you type (up to 10, with customer, site, group and OS); choose one (or use
the arrow keys and Enter) to open the device. Its customer becomes the selected customer.

To browse or filter instead:

1. Choose **Devices**, select an authorized customer.
2. Search by exact/partial hostname, VSA asset ID, site or group. Add OS, device type or last-seen filters.
3. Open a device record. Confirm source instance and last collection time.
4. Use tabs: Overview, Hardware, Installed Software, Windows Updates, Documentation (if linked), Tickets (if linked), History.
5. Use `Open in VSA` when supported to investigate directly in the system of record.

**Fresh details for one device:** updates, policies, notifications and custom fields are fetched once a day (updates,
notifications) or once a week (policies, custom fields), and only for devices that were online. If you need them now,
for example after patching, open the device and press **Refresh details now** (needs sync permission). The sync starts
straight away and fetches that device's details.

**Do not** treat a device missing from the portal as definitely absent from VSA until the last full sync completed successfully and source mapping is verified.

## 4. Identify out-of-date third-party software

1. Open **Software → Third-Party Compliance**.
2. Select customer, vendor/product (e.g. Chrome, 7-Zip), status `Outdated`, and optional site/group.
3. Review installed version, reference version, catalog revision, reference source, release channel and comparison reason.
4. Use `Unknown` view to investigate unmapped applications, unsupported version schemes or missing catalogs.
5. Export current filtered results for investigation.

`Outdated` means a comparable installed version is below a reviewed catalog reference. It does **not** mean a third-party patch is confirmed applicable/available through VSA, nor does it prove a vulnerability. `Newer than reference` might indicate the catalog is stale. If uncertain, escalate catalog review; do not blindly deploy patches.

## 5. Windows OS updates

Open **Patch Management → Missing Updates** (or Windows Updates). Filter by KB, OS, device, available/installed state and reported severity. The source is VSA X `AvailableUpdates` and `InstalledUpdates` where provided. Some devices may have unsupported or missing update data. Empty data is not equivalent to fully patched.

## 6. IT Glue reconciliation

Open **IT Glue → Reconciliation**. Filter matched/unmatched/ambiguous configurations. Review source IDs, serial number evidence, and match method. An apparent match is informational until explicitly reviewed. Authorized admins can approve links; ordinary users must not merge or modify IT Glue objects.

## 7. Autotask PSA ticket analysis

Open **Autotask PSA → Tickets**. Filter by customer, status, priority, created/updated period. View ticket details sanitized for the reporting context and follow a source link for full authoritative detail. Device relationships exist only when IDs have been verified or manually approved. Ticket information is read-only.

## 8. Generate and schedule reports

1. Open **Reports → Report Builder**.
2. Choose report type and authorized customer.
3. Set time range, filters, columns and format.
4. Inspect preview and the freshness/provenance panel.
5. Generate asynchronously; monitor job progress.
6. Download when complete. If a report is stale or incomplete, label that in downstream communications.
7. Save a view or request a schedule only if your role permits.

Exports can contain sensitive operational data. Use approved storage and recipients. Download access can expire or be revoked.

## 8a. Onboarding check (expected device list vs VSA X)

1. Select the customer, open **Onboarding check**, and confirm the snapshot line shows a recent sync.
2. Upload the customer's list (.xlsx or .csv, at most 5 MB). Pick the worksheet and header row, then check the suggested
   column mapping. Map at least one identifier: source device ID, serial, FQDN, hostname, MAC or IP.
3. Review the preview. Malformed values are marked, and formula cells are ignored, never calculated.
4. Start the comparison and open the result. The tiles count each classification. **Not found** means no match in
   this snapshot. It does not prove the agent is missing.
5. Use **Needs review** to resolve ambiguous rows (several devices, or a MAC/IP-only hit) by choosing the right device.
   Your decision is recorded next to the automatic result, which is kept unchanged.
6. Download the workbook (XLSX) or CSV. Wrong-group devices must be moved in VSA X through the approved change process;
   the portal does not move devices.

## 8b. Patch policies

**Patch policies** shows which VSA X Patch Management policy each device has. The page keeps these cases apart:

* **assigned**: a policy is assigned to the device.
* **No Policy (explicit)**: someone deliberately configured "No Policy".
* **No Patch Management entry**: VSA X reported nothing for this device. This does not mean "no policy".
* **unknown**: the policy data was not collected.

Policy rules describe configuration, not what was installed. Drift appears only once an administrator-approved
expectation covers the device. Each device's **Policies** tab shows its applied policies and the rules of its patch
policy.

## 8c. Device health

**Device health** groups devices on six dimensions: connectivity, agent installed, agent version, system disk free
space, antivirus and firewall.

* Each dimension covers every device, so its counts add up to the total.
* "Unknown", "not reported" and "not collected" are separate rows. They are neither healthy nor unhealthy.
* Click a row to list those devices.
* All values come from the last VSA X snapshot, not live monitoring.
* The thresholds banner shows whether documented defaults or customer-approved values are in use.

## 8d. Inventory changes

**Inventory changes** compares two complete VSA X snapshots; by default it uses the current one and the one before it.
It lists:

* devices that appeared or disappeared;
* changes to hostname, group, site, OS, agent version, IP addresses and installed software.

The window shown is between the two sync times. It is not when the change happened, and no person is named. If a
section was missing in either snapshot, that device is listed as "not compared" for that section.

## 9. Interpretation reference

| State | Meaning | Appropriate action |
|---|---|---|
| Current | Comparable installed version matches reviewed reference | No version gap detected; not proof of security |
| Outdated | Installed version lower than compatible reviewed reference | Investigate patch applicability using authoritative systems |
| Newer | Installed version higher than catalog reference | Review catalog freshness |
| Unknown | Missing/mismatched reference or comparison failed | Review mapping/source |
| Unsupported | Product/platform not covered by comparison policy | Track as unsupported, not current |
| Excluded | Approved exception recorded with owner/expiry | Review exception at expiry |
| Stale | Source information beyond freshness limit | Re-synchronize or qualify report |
| Data unavailable | API did not provide supported evidence | Do not infer zero findings |

## 10. Common questions

**Why doesn't the portal show every workstation?** Check current source mapping, last successful sync, disabled sites, source API permissions, and quarantine errors.

**Why is Chrome marked Unknown?** Product, channel, architecture or version may not map to a reviewed catalog entry.

**Can I deploy patches from this portal?** No; v1 has no vendor write actions.

**Why did this month's historical compliance differ from a new report for the same date?** Historical report uses pinned source and catalog generations; a new run may use a newer catalog unless the user explicitly selects a historical revision.

## Generic installations and group suggestions

On an explicitly marked onboarding group's page, **Suggested destinations for onboarding devices** lists each device and its evidence. Approved subnet matches come first, subnets observed on existing destination devices second, naming-only hints last. Search/paging includes devices with no match. Each hint explains its IP/CIDR or naming token; multiple candidates need review. Click a device to open Operations. Administrators can propose additional destination subnets on the destination group's Network review panel; only approved rules are labelled Approved subnet. See ONBOARDING_SUGGESTIONS.md.

A device may legitimately remain in an onboarding agent group after generic installation. Open its **Operations** tab to see reviewed CIDR-based destination hints, matching reported addresses and any overlapping candidates. A missing match does not indicate incorrect placement. VPNs and shared networks can create misleading matches; check policy inheritance and customer/source identity. Choosing **Use [group]** fills the target only. Portal review records a proposal; an administrator transfers the agent manually in VSA.

## Faster device lists and group navigation

Use Devices search for a hostname, serial, source ID, MAC or IP; typing stays immediate while requests settle. Select a named site or a quick filter, open More filters for group/OS/type/last-seen window, and remove individual active chips. Click Device, Group, OS or Last seen column headers to sort. Columns and Density change presentation; Rows per page, First/Last and Go control paging. Updating rows temporarily stop accepting actions until replacement results arrive.

Open Saved views to name the current filters, visible columns, density and page size. Views are private by default; explicitly share when appropriate. Load a view, Update view to revise your own, or Delete view and confirm. Current presentation also survives a device investigation through its return URL. Exports use the report's defined columns.

Groups & network starts with a searchable group list. Search names, site, organization, source or ID, refine by site/purpose, click a device total for the exact source population, or open a group name for network evidence. The Hierarchy tab retains organization/site/group browsing. Onboarding labels identify legitimate temporary destinations; transfers remain manual.

## Software and Windows-update workspaces

Software opens Overview. Find a product or click a classification/product count to investigate Installations; Exceptions has its own tab and retains administrator controls. Installation search includes name, publisher, version and device hostname. Use Classification and Product to narrow the population, Columns to adjust the table, and Export installations for all matching rows.

Windows updates starts with Update records. Search title, KB or device and refine by state/severity. Common updates shows frequent available KBs; click one to open matching records. Collection coverage shows one row per device, including unknown/failed/unsupported evidence. Find device searches hostname/source ID; filter the available-update collection state and page through the complete population. Export device coverage exports these device rows, while Export update records exports device-by-update rows. Summary tiles always describe the full current customer snapshot.

Clicking a device opens its relevant investigation tab. Back to software or Back to Windows updates restores the originating search/page; reload also retains URL filters. Reported zero requires collected evidence; Unknown never means zero. This portal does not deploy patches or establish third-party missing-patch applicability.

## Compliance baselines

**Compliance** (under Overview) checks every device of the selected customer against your own standards. A customer
administrator creates a baseline (for example "Workstation standard") and adds rules: required or forbidden software,
minimum OS version, antivirus and firewall, disk space, days since last seen, agent version, outdated software,
Critical OS updates and patch policy. Each device is *compliant*, *not compliant* (with the failing rules and the
reason) or *unknown* (VSA X did not report the data a rule needs). The score is compliant ÷ (compliant + not
compliant). Select a rule to list only the devices that fail it. Results always reflect the latest snapshot; nothing
is changed in VSA X.

## Third-party patching

**Software → Third-party patching** lists programs with outdated installations (compared with the reviewed software
catalog) and, for each, whether the device's VSA patch policy has a software rule for it. *No rule in policy* and
*No patch policy* are the gaps to act on. *Rule in patch policy* only means the policy is configured to handle the
program: the VSA X API does not report whether the update was actually deployed, so the portal never shows it as
done. Programs without a catalog entry are not compared; a super administrator adds them under Settings → Software catalog, most quickly from the VSA application catalog (the versions VSA's 3rd-Party Patching deploys). Once a program is approved, the portal keeps its version current automatically every day.

## Subnets

**Groups & network → Subnets** lists every subnet seen on the customer's devices (from addresses reported with a
subnet mask): how many devices, which groups and sites they are in, gateway and DHCP use, and whether the subnet is
approved for a site or group. A subnet that spans several groups or has devices *outside* its approved group points
to devices that may be in the wrong group. Customer administrators can propose the main group as the subnet's
approved group with one click; once approved it improves onboarding destination suggestions. Subnets describe what
endpoints report, not the physical network.

## Custom reports

**Reports → Custom report** builds your own report in four steps: pick the data (devices, health, software, Windows
updates, compliance, third-party patching or subnets), tick the columns, add filters (for example *Disk is
critical*, *Days since seen ≥ 14*, *Program contains Chrome*, *Version state is outdated*), and choose the sort and
format (Excel, CSV or PDF). **Preview** shows the first 100 rows. **Generate report** creates the file and offers
**Download** on the same page when it is ready. **Send this report regularly** saves it and adds a daily, weekly or
monthly schedule with recipients in one step (or *Save without schedule*). Every file states its data source, snapshot time, filters and limitations.

## Monthly customer scorecard

Open the customer and select **Monthly scorecard (PDF)** on the Summary tab, or choose *Customer scorecard
(monthly)* under Reports → New report (also in Excel or CSV) and schedule it monthly under *Definitions &
schedules*. It lists the key measures for the customer - devices, health issues, Critical updates, outdated
software and patch-policy gaps, end-of-support systems, compliance scores and network findings - with the value
about 30 days earlier where history exists, and states the date it compares with.

## Cleanup

**Cleanup** (VSA operations) lists housekeeping work for the selected customer: devices sharing a hostname, serial
number or MAC address, agents not seen for a chosen number of days or never, devices in no group or still in an
onboarding group, devices without an agent and devices without a usable serial. Select a category to narrow the
list and download it as a CSV to-do list. Fix the items in VSA X; the list updates after the next sync.

## Alerts

Open **Alerts** with the bell in the top bar. Under **My watches**, choose a customer and what you want to hear
about: a new device, a device not seen for a number of days, a disk turning critical, a program appearing (for
example remote-access tools) or a compliance score dropping below a percentage. After each sync you get one alert per
watch listing only what is new since the last check. Pause or remove a watch at any time. Alerts stay in the portal;
email is not enabled.

## All customers

**All customers** (Overview) shows every customer you can access side by side: devices, offline devices, critical
disks, antivirus issues, Critical updates, outdated software, the lowest compliance score and whether the data is
up to date. Click a column to sort, download the table as CSV, or select a customer to open its Summary.

## Automation

**Automation** (VSA operations) shows how VSA X workflows ran on the selected customer's devices: runs, failures and
success rate per workflow, and each failed run with the device and the step that failed. Pick a workflow to see only
its runs. Super administrators also see the catalog of tasks and workflows. VSA X does not report scheduled *task*
results through its API, so those are not shown. Add the alert "An automation workflow fails on a device" under
Alerts → My watches to be told about new failures.

## Script data

VSA scripts can report values the inventory does not have (for example BitLocker state or local administrators). A
super administrator selects such scripts under **Settings → Script collectors** and lists which output variables to
keep. The values appear on the device page (**Script data**), can be used in compliance baselines ("A value collected
by a VSA script matches") and in custom reports ("Script results").

## Details from VSA (organisation, site and group custom fields)

Custom fields set on the VSA organisation, its sites and groups (for example contract tier or site contact) appear
on the customer page as **Details from VSA**, and in custom reports ("VSA custom fields (organisation, site, group)"). Only field
names approved for that customer under the custom-field allowlist are read and stored; nothing is requested until a
name is approved.

## Scopes and patch global rules

Super administrators see, under **Automation → Catalog**, every VSA scope with what it matches, how many devices it
covers and which tasks or workflows use it (scopes used by nothing are flagged), plus the tenant's patch global rules.
A global software rule counts as third-party patch coverage ("Global rule") for devices that have a patch policy
assigned. This is configuration only: whether VSA deployed an update is not available from the API.

## One authorization

Administrators do things in one step (since 2026-11-24): what you save takes effect straight away and is recorded in
the audit log as proposed and approved by you. This covers expected subnets, health thresholds, patch policy
expectations, approved custom field names, software lifecycle entries, catalog imports and aliases, custom field changes
and group moves. Buttons therefore say **Add**, **Save** or **Move** rather than **Propose**. Engineers still suggest
changes that need an administrator, and a customer administrator's source mapping waits for a super administrator. If
your server is set to require a second approver, the screens say **Propose** and a different administrator approves.

## Moving devices to another group

**Administrators move in one step** (since 2026-11-24). No proposal, approval or verify step:

- **One device:** open the device → **Operations** → pick the destination (or press a suggested group) → **Move in VSA
  X…** → **Move now**. The result appears right there (*Moved in VSA X*, or why not).
- **Onboarding:** on an onboarding group's *Destinations* view, each destination lists its devices with tick boxes:
  tick **Move N devices to <group> in VSA X now** and press **Move N devices now**. Progress and the result per device are
  shown; if VSA X answers OK but does not apply moves, it stops after the first device.
- **Engineers** cannot move devices; they press **Suggest move** (with a reason). Suggestions wait under **Group moves**,
  where an administrator selects them (header box selects all) and presses **Move in VSA X (N)** or **Reject (N)**, or
  opens one and presses **Move in VSA X…**. A note is optional.

Every step is still recorded in the audit log (proposed, approved with `self_approved`, sent, result). When the server
requires a second approver (`REQUIRE_SECOND_APPROVER=true`) or moving is not switched on for the integration, the
portal falls back to suggestions and approvals and says why.

When execution is enabled for the VSA X integration, an approved proposal shows **Execute move in VSA X…** under
**Group move proposals → Review proposal**. An administrator with approval permission (not the requester when a second approver is required) confirms the
move; the portal sends it to VSA X once and then reads the device back:

- **Moved in VSA X** - VSA X accepted it and the device now reports the destination group.
- **Not confirmed yet** - VSA X accepted it but the device still reported the old group; press **Verify in VSA X** later.
- **Outcome unknown** - VSA X did not answer clearly (the reason is shown). It is not sent again automatically;
  press **Verify in VSA X**.
- **Not moved** - VSA X refused it (propose again if needed), or reading back showed the device still in its old
  group: then **Execute move in VSA X…** is offered again, because sending the same move again is safe.
- To check many sent moves at once: **Group move approvals → Sent, not confirmed**, tick the header box and press
  **Verify in VSA X (N)**. Each device's group is read back; nothing is sent again.
- **Not moved - VSA X answered OK but did not apply the move** - the device is still in its old group although VSA X
  said OK. Usually the API token may not move devices, or a proxy/firewall in front of VSA X answers instead of the API.
  An administrator fixes that, then sends the move again. A bulk move stops at the first such answer.
- **Nothing was sent** - the portal server could not reach VSA X (for example its name could not be looked up). The
  message says why; the move stays approved and can be sent again once the server can reach VSA X.

Execution is refused when the approval is older than 24 hours, the device has changed group since it was proposed,
the destination group is no longer active, or the inventory is stale. When execution is not enabled the page says why,
and the move can still be made manually in VSA X.

## Custom fields (assign VSA X custom fields to workstations)

**VSA operations → Custom fields** sets an existing VSA X custom field (for example *PatchRing*) on workstations.
Only fields an administrator made editable are offered; the value box matches the field type (text, number, true/false,
date).

1. **Choose the devices.** *Device assignments*: filter and tick devices (the selection stays while you page), or use
   all devices matching the filters. *Import list*: paste names (one per line, or separated by commas or semicolons) or
   upload TXT, CSV or Excel and map the columns (device ID, serial, FQDN, hostname, expected site/group, optionally a
   value per device).
2. **Review the matches.** Matched, not found, several matches (choose the right device), duplicate, invalid, another
   customer, or not a workstation (servers are excluded). Nothing is changed yet. When no line needs a choice, the
   preview starts by itself; otherwise choose the devices and click *Preview changes*.
3. **Preview.** The portal reads the current value from VSA X for every device: *Assign* (no value set on the
   device; an inherited organisation/site/group value is shown and left unchanged), *Update* (a different value is set
   on the device), *Already correct*, *Requires review* (could not be read) or *Blocked*.
4. **Apply (administrators only).** Engineers prepare and preview a job; a customer administrator then opens it under
   from **Waiting for you to apply** at the top of the Custom fields page, checks the preview and applies it with one
   confirmation (which also names how many devices have a different value that will be overwritten). A preview older
   than 30 minutes is refreshed automatically when the job is opened. When you are an administrator, **Apply changes** also approves the job (one step); it only waits for a second administrator when the server requires one (`REQUIRE_SECOND_APPROVER`). Progress is shown; you can cancel the devices not started yet.
5. **Results.** *Verified success* only when the value was read back from VSA X. *Unknown outcome* means VSA X did not
   answer clearly; the change is never sent twice. Download the results (Excel with Summary, Successful, Skipped, Failed,
   Not found and Ambiguous sheets, or CSV), and *Prepare a new job for the failed devices* if needed.

**Placeholder for all devices (for example "TBD").** Use this to put a custom field on every workstation before the
final values are known:

1. Open the **Placeholder for all devices** tab, choose a text field, keep the value *TBD* (or type another), and
   optionally limit it to one site or group. The page says how many devices will be checked.
2. **Review devices** prepares the usual preview. Only devices with **no value** get the placeholder. A device that
   already has any value, set on the device or inherited from its organisation, site or group, is shown as *Already
   has a value; left unchanged* and is not touched. Servers are never changed.
3. Apply it as usual. A value someone sets in VSA X after the preview is also left alone (the device is re-read just
   before each write).
   If **Apply changes** stays grey with *Nothing to apply*, every device already shows a value; the list says why.
   *Has a value from the organisation, site or group* means VSA X sets the field above device level (or for the whole
   field), so those devices are left alone. To put the placeholder on them anyway, use *Device assignments* (it sets a
   device value; the inherited value stays in place).

**Find devices by a custom field.** On **Devices → More filters**, and above the device list in *Device assignments*,
**Filter by custom field** with a condition: *is empty*, *is empty or…*, *is…* (for example *TBD*), *has a value other
than…*, *has any value*, or *was not read in the last sync*. To set the final values, filter the field *is… TBD*, tick
*Use all devices matching these filters*, enter the final value and review. The filter uses the values collected by the
latest sync, so it lists only field names a customer administrator approved under **Customer → Custom fields** (only
those values are collected). Devices whose values were not read are never counted as empty. After a job, the devices it
changed are re-read on the next sync.

A job holds at most 5,000 devices (`CUSTOM_FIELD_MAX_JOB_ITEMS`); for a larger customer, run the placeholder per site.

The device page has a **Custom fields** tab with the editable fields' current values and the same reviewed change for that
one device. **Assignment history** lists every job. The portal never removes a custom field or changes organisation,
site or group values.

## Servers & owners

**Servers & owners** (Software & patching) shows the selected customer's servers, who owns them and what each needs:
available OS updates (Critical and Important first), whether a patch policy is assigned, outdated programs, whether the
operating system is out of support or ending soon, and devices not seen for more than 30 days. "Action needed" says it
in words; tick **Needs attention only** to see just those.

- **Which devices are servers:** devices whose operating system name contains "Server" are detected automatically.
  Choose **Show → All devices** to mark others (for example Linux servers) with **Mark as server**, or use
  **Not a server** for a detected device. **Use detection** returns a device to the automatic rule.
- **Owners:** on **Owner groups**, add a group with the owner's name and email, then select servers on the Servers tab
  and **Assign owner**. Customer administrators can change markings and owners; everyone with access can view them.
- **Informing owners:** **Report (PDF)** produces *Server patching - <group>* for that owner (also available under
  Reports as "Server patching by owner", for all owners or servers without an owner). **Email owner** opens your mail
  program with a summary of that owner's servers that need attention; attach the PDF and send it yourself.
- **Every month:** **Schedule monthly** on an owner group produces that owner's PDF on the 1st at 07:00 (your time
  zone); it appears under Reports. Change or stop it under **Reports → Definitions & schedules**. On the Reports page
  the *Server owner group* filter lists the customer's owner groups.
- The customer **Summary** shows a *Servers* card, and the monthly scorecard has a *Servers* section (servers needing
  patching or an upgrade, servers without an owner).

Markings and owners exist only in this portal; nothing is changed in VSA X.

