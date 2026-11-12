# Reporting specification, metric semantics and exports

**Guiding rule:** A report must be reproducible, customer-scoped and honest about what the source API proves. Version mismatch ≠ verified missing third-party patch ≠ vulnerability.

## 1. Reports in v1

| ID | Report | Required filters | Core columns |
|---|---|---|---|
| RPT-01 | Asset inventory | Customer, site, group, OS, last seen | device ID, hostname, type, OS, agent, last seen, source-as-of |
| RPT-02 | Installed software | Customer, product/publisher, version, device | device, product, publisher, installed version, observation timestamp |
| RPT-03 | Software version compliance | Customer, product, state, device | installed/reference version, channel, classification, reason, catalog revision |
| RPT-04 | Available OS updates | Customer, KB/severity, device | device, KB, title, OS update state, source-as-of |
| RPT-05 | Software version distribution | Customer, product | version, installations, unique affected assets, unknown count |
| RPT-06 | Offline/stale devices | Customer, site, stale threshold | last seen, age, collection freshness, eligibility |
| RPT-07 | IT Glue reconciliation | Customer, match state | source IDs, hostname/serial, match method, mismatch |
| RPT-08 | PSA ticket summary | Customer, status/priority, period | source ticket ID, status, priority, owner, timestamps |
| RPT-09 | Historical trends | Customer, report periods | period, numerator, denominator, as-of, change |
| RPT-10 | Sync health and coverage | Customer/integration/date | jobs, errors, published generation, quarantined rows, staleness |

## 2. Definitions and denominators

### Unique asset count
`COUNT(DISTINCT asset.id)` for current published generation, filtered by authorized customer(s), optionally active assets. Present inclusion rule (e.g. last seen within X days). Source duplicates across integrations must never be silently merged.

### Unique devices with outdated software
`COUNT(DISTINCT asset_id)` where at least one installation has state `outdated` under the selected published catalog revision. A device is counted **once**, regardless of number of outdated applications.

### Outdated software installations
Number of **installation records** classified outdated. Different from unique device count; show both.

### Comparable software coverage
`comparable installations / eligible software installations`, where comparable means product mapped to a reviewed compatible catalog revision and version comparison succeeded. **Unknown** must remain in denominator for coverage, not be counted as compliant.

### Software version compliance
`current comparable installations / (current comparable installations + outdated comparable installations)` ×100. Display unknown, unsupported, excluded, newer-than-reference and data-stale populations **separately**. Never call this patch deployment compliance.

### Device-level software compliance
`eligible devices without outdated installations / eligible devices with fully evaluated inventory` ×100, with explicit inventory-completeness rule; unknown devices are not automatically compliant.

### OS missing update counts
Based on actual VSA `AvailableUpdates` records and scan source time. Severity only if reported. Unsupported/unscanned devices are reported separately; do not infer zero missing updates from an absent array.

### Ticket resolution time
When timestamps are available, compute duration from configured start to resolved/closed event. Define business-hours vs elapsed-hours and excluded statuses; do not infer SLA compliance without agreements and calendars.

## 3. Report provenance block (mandatory)

All report files and previews must include:

```text
Customer: <approved customer display name and code>
Reporting period: <start UTC> to <end UTC>
Generated: <UTC timestamp>
Datasets: VSA assets generation <id>, IT Glue <id/NA>, PSA <id/NA>
Source last successful sync: <per-source timestamp>
Applied catalog revision: <id and approval date or NA>
Filters: <normalized filter set>
Records included: <count>
Records unknown/stale/unsupported/excluded: <counts>
Limitations: <explicit caveats relevant to the report>
```

Never hide missing data by rendering `0`. If the dataset is stale, label it prominently.

## 4. Software version comparator policy

A catalog entry is compatible only if product, publisher, channel/edition, OS platform and architecture criteria match. Use product-specific comparator rules for 4-part Windows versions, semver, date-based versions and vendor variants. Record `algorithm_version`, source reference URL, review timestamp, `reason_code`. A release with ambiguous suffix/channel is `unknown`; a newer installed version is `newer_than_reference`, not automatically safe or unsafe. Exemptions/approved exclusions require approver, reason and expiry.

Do not scrape arbitrary websites without explicit permission. Do not label software as "vulnerable" unless a verified vulnerability feed is integrated and the detection is justified.

## 5. Report builder and templates

Inputs: customer scope, template ID, report-period timezone, filters (allowlisted), selected columns, grouping, sort, format, optional schedule. Saved views can be private or shared only according to RBAC. Asynchronous report jobs pin source generations at enqueue time or before execution, with a consistent snapshot.

Generate:
- CSV: RFC-compliant quoting, UTF-8, prevention of spreadsheet formula injection, no unauthorized fields.
- XLSX: formatted tables, frozen headers, filters, clear numeric/date types, worksheet splits if needed, legends/provenance sheet.
- PDF: cover, short executive summary, KPI methodology, charts, detailed pages or linked supplemental CSV/XLSX; page numbers and source metadata.

Filename pattern: `ODYSSEY_<customer-code>_<report-id>_<period>_<run-id>.<ext>` with sanitized tokens. Never expose internal filesystem paths.

## 6. Schedules and distribution

Support on-demand, daily, weekly, monthly runs; timezone-aware scheduling with DST; idempotency per schedule/period; configurable send time. Before sending, validate customer-recipient authorization and contract permissions. Prefer access links to protected artifacts over unencrypted attachments unless policy approves email delivery. Log generation, access, delivery, failures and retention expiry.

## 7. Sample UI cards (definitions only, not live values)

- Devices observed in current published VSA generation.
- Devices with at least one outdated application (comparable catalog only).
- Installed applications requiring reference-catalog review.
- Devices with available OS updates (VSA-supported fields only).
- Last successful sync, source freshness, sync failures.

Cards must link to filtered record lists. All chart totals must reconcile to underlying tables using the same filters and generation IDs.

## 8. Acceptance criteria

1. CSV/XLSX/PDF for RPT-01–04 can be generated from fictional fixtures with complete provenance.
2. A user cannot request another customer's report or previously generated file.
3. Totals reconcile between dashboard, list API and exported data.
4. Missing observations yield unknown/stale, not compliant.
5. Historical reports remain reproducible after new sync/catalog revision.
6. Oversized exports are queued, bounded and time-limited.
7. Injection/sanitization tests pass for hostile filenames and cell contents.
