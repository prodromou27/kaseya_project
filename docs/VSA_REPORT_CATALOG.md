# VSA-only report definitions, filters, quality and exports

All reports are customer-scoped, use pinned **complete** inventory generations, show UTC generated time (viewer local time optional), source observed time, catalog revision, filter/denominator definitions and exclusions. Reports must never claim stale/unknown data is zero or compliant. Redact sensitive fields not on the per-customer approved allowlist.

| ID | Report | High-value fields / questions |
|---|---|---|
| R01 | Customer inventory | device ID/name, OS, type, site/group, last seen, agent |
| R02 | Workstations & servers | OS, manufacturer/model, serial, IP and agent version |
| R03 | Installed software | publisher/product/version, count, associated devices |
| R04 | Outdated software versions | installed vs reviewed reference, channel, reason, catalog time |
| R05 | Third-party patch status | only documented and live-verified applicability/deployment fields; otherwise unavailable banner |
| R06 | Windows available updates | device, KB, title, severity, source time |
| R07 | Windows installed updates | device, KB, installation date if source supplies |
| R08 | Policy coverage/drift | assigned policy, explicit no-policy, baseline mismatch, unknown |
| R09 | Agent health | last seen, days stale/offline, client version, inventory recency |
| R10 | Group network facts | interfaces, IP/MAC/mask/gateway/DNS, derived CIDR |
| R11 | Network anomalies | duplicate address and out-of-scope subnet observations |
| R12 | Excel onboarding reconciliation | expected, matched, wrong site/group, missing, ambiguous, unexpected |
| R13 | Disk & hardware capacity | disk free%, sizes/source time, CPU/memory details if present |
| R14 | Security observations | AV/firewall/UAC/ransomware raw state and unknown |
| R15 | Notifications | device, category/status/time where supported |
| R16 | Inventory changes | newly observed, group/OS/network/software changes; two generations |
| R17 | Software / OS lifecycle | vendor-supported lifecycle reference date and affected devices |
| R18 | Group move proposals & results | before/after, request/approval/verification state |
| R19 | Sync health & coverage | successful runs, source errors, stale/quarantined rows, last good generation |
| R20 | Executive VSA operational summary | KPI definitions, coverage, unknowns, notable exceptions and trend |

### Universal filters

Customer (mandatory or authorized global), VSA instance, organization, site, group, device class, OS, software, version, policy, observation status, date range, last seen, agent version. Save per-user or explicitly shared filter presets with permission checks.

### Exports and scheduling

- CSV (safe escaping), XLSX (multi-sheet, typed columns), PDF (summary+detail and print layout).
- Async report job, status/progress, private storage, expiring authorization-controlled download.
- Saved report definitions and schedules; customer-aware SMTP recipient allowlists and approved delivery policy.
- Every export contains source provenance, source generation, comparison/catalog version and known gaps. Export only authorized columns and rows.
- Compare two historical generations only when source coverage/denominator is comparable; flag changed population.

### Example KPI calculation contract

`Affected devices with outdated versions`: count distinct devices with >=1 `OUTDATED` software install and a known compatible catalog reference. Count total installations separately. Provide `eligible device denominator`, `unknown catalog`, `stale inventory`, `excluded`. Never report "pending third-party patches" from that number.
