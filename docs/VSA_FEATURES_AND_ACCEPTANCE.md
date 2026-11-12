# VSA-only functional feature catalog and acceptance requirements

All features are for **Phase 1** and must be customer-scoped. Priority: **P0** must have for initial engineer pilot; **P1** must have before broad read-only rollout; **P2** follow-up inside VSA-only phase if supported. `GATED` means independent approval or live capability required.

| ID | Area | Requirement | Priority | Acceptance |
|---|---|---|---|---|
| VSA-F01 | Dashboard | customer counts, coverage, agent stale, software outdated, OS update status and sync freshness | P0 | KPI click-through, valid denominator |
| VSA-F02 | Device list | search hostname/FQDN/serial/MAC/IP, filters and saved columns/views | P0 | server-scoped pagination and RBAC |
| VSA-F03 | Detail | tabs for overview, hardware, network, OS, software, patch/policy, agent/security, events, history, reconciliation | P0 | raw facts tied to source and timestamps |
| VSA-F04 | Hierarchy | customer > organization > site > group | P0 | stable IDs, member counts, multi-customer isolation |
| VSA-F05 | Software | installed version, publisher, editions and normalized identity | P0 | no fictitious releases |
| VSA-F06 | Catalog | administrator-reviewed product/channel/version reference, revision/evidence | P0 | unknown version stays unknown |
| VSA-F07 | Version status | current/outdated/newer/unknown/unsupported/excluded | P0 | correct non-SemVer and channel handling |
| VSA-F08 | OS patches | available/installed KBs, counts, date/severity from source | P0 | no claim missing third-party patch |
| VSA-F09 | Policies | applied patch policy and settings, no policy/unknown, drift vs reviewed expected | P1 | assignment vs deployment distinguished |
| VSA-F10 | Pending 3rd party | exact patch target/approval/deployment/reboot/failure | GATED | only enable after supported source verified |
| VSA-F11 | Onboarding | XLSX/CSV import/preview/map/deduplicate/reconcile/export/history | P0 | every row categorized with reason |
| VSA-F12 | Group network | all NICs/IP/MAC/masks/gateways/DNS and group rollup | P0 | multi-NIC/IPv6 supported |
| VSA-F13 | Network anomalies | duplicate IP/MAC, unexpected subnets, missing network data | P1 | flag review, not topology proof |
| VSA-F14 | Agent health | stale, offline, old agent, inventory age, missing policy | P0 | configurable thresholds and source freshness |
| VSA-F15 | Capacity | disk free %, CPU/memory where reported, alert thresholds | P1 | no live-telemetry claims from inventory |
| VSA-F16 | Security observations | antivirus/firewall/UAC/ransomware observations, data age | P1 | unknown != secure/insecure |
| VSA-F17 | Notifications | per-device notifications and recurring patterns | P1 | source pagination and time filter |
| VSA-F18 | Changes | newly observed devices, group/IP/software/agent changes between *complete* generations | P1 | actor attribution only with authoritative audit |
| VSA-F19 | Lifecycle | OS/software support dates from approved official catalog | P2 | unknown dates not invented |
| VSA-F20 | Reports | saved/scheduled device, patch, software, group, onboarding and changes reports | P0/P1 | filtered, as-of, reproducible files |
| VSA-F21 | Group move | one-device propose/approve/execute/readback | GATED | independent approval, one PUT, auditable and reversible plan |
| VSA-F22 | Operational audit | user downloads, sync, catalog changes, move lifecycle | P0 | customer/source/actor and result recorded |
| VSA-F23 | Advanced Reporting | evaluate patch & site-map datasets for unsupported public API gaps | P2 | only through supported machine integration |
| VSA-F24 | Summary of group assignment | expected group vs observed VSA groups, user-confirmed corrections | P0 | reconciled changes never auto-applied |
| VSA-F25 | Custom fields/tags | approved source fields and tag filters | P1 | default deny sensitive field names/values |
| VSA-F26 | Source health | run logs, coverage %, last complete snapshot, API throttle/errors | P0 | failure does not delete last complete data |

## Mandatory detailed device page

- Header: customer, source instance, device GUID, hostname, org/site/group, sync badge.
- Overview: operating system/build, agent version/last seen, status, manufacturer/model, serial and approved tags.
- Software: installed apps, versions, classification, reference catalog version and time, policy relationship if supported.
- OS Updates: available/installed OS updates; scan freshness and policy status; documented UI states vs API data.
- Third-Party Patch: **not verified** until exact applicable/deployment feed exists; prominently display source limitation.
- Network: all NICs and addresses, mask/gateway/DNS/DHCP, duplicate/out-of-policy observations.
- Hardware: disks/free space, memory and CPU from snapshot; source timestamp.
- Security: observed antivirus/firewall/UAC/ransomware fields with unknown state.
- Policy: applied VSA policies, explicitly configured `No Policy`, baseline drift where source supports.
- Notifications: source-backed events, filters, timestamps; don't claim all security incidents.
- Changes: observed differences, audit correlation if available, onboarding match and movement history.

## UX requirements

Compact tables and quick drilldowns; customer selector; organization/site/group tree; persistent filters; sortable columns; global search; role-aware controls; honest empty/stale/unavailable states; responsive layout. No dummy success metrics in production. Demo data must be visibly labeled.
