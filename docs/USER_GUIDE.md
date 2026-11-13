# Engineer and viewer user guide

**Purpose:** Help internal authorized users interpret reports correctly. **Status:** Planned UI workflows, not existing screenshots or deployed instructions.

## 1. Signing in and selecting a customer

Access the Odyssey internal portal using the approved HTTPS URL. Sign in with organizational SSO/MFA when configured. Choose a customer from the selector; only assigned customers should appear. A global aggregated view is available only to explicitly authorized global roles. Always confirm the selected customer before exporting.

## 2. Dashboard

The dashboard summarizes device inventory, installed software, version-compliance classifications, OS update availability and integration health. Each card links to a filtered list. Every metric must display the **data-as-of** timestamp and warn if the source is stale or incomplete. **Unknown** means no justified classification, not automatically compliant.

## 3. Find a workstation or server

1. Choose **Assets → All Devices**, select an authorized customer.
2. Search by exact/partial hostname, VSA asset ID, site or group. Add OS, device type or last-seen filters.
3. Open a device record. Confirm source instance and last collection time.
4. Use tabs: Overview, Hardware, Installed Software, Windows Updates, Documentation (if linked), Tickets (if linked), History.
5. Use `Open in VSA` when supported to investigate directly in the system of record.

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
