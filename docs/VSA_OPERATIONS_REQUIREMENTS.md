# VSA X Operational Requirements — Expanded Scope (VSA-OPS)

> **PHASE 1 OVERRIDE (2026-11-12):** Kaseya VSA X **only**. For current implementation scope, obey `docs/PHASE1_SCOPE.md`, `docs/PHASE1_TASKS.md`, `docs/PHASE1_IMPLEMENTATION_PLAN.md` and their specialized VSA documents. Any discussion below of IT Glue, Autotask PSA, Tenable, or MCP is **future design context, not a Phase 1 implementation requirement**. A device group move is the only proposed vendor write and is disabled by default.


**Status:** Approved for design/backlog; **not implemented**. **Updated:** 2026-11-12.  
**Product:** Odyssey Kaseya Analytics & Reporting Portal (standalone, multi-customer; not Managed Services Hub).  
**Primary source:** Kaseya VSA X / VSA 10 on-premises or hosted REST API v3.  
**Priority:** VSA X depth before IT Glue/Autotask breadth.  
**Write policy:** Vendor API remains **read-only by default**. The sole proposed write is **device group movement**, which must use a separately authorized, separately enabled approval workflow and write-capable credential. No patch execution, remote commands, policy editing, script running or agent deployment.

## 1. Operator use cases / acceptance criteria

| ID | User story | MVP requirement | Evidence/acceptance |
|---|---|---|---|
| VSA-01 | Find any PC by hostname/FQDN, site, serial or MAC | Yes | Indexed scoped search, source/last-seen, no cross-tenant leak |
| VSA-02 | See PC installed software and versions | Yes | VSA `/assets` InstalledSoftware; time-stamped |
| VSA-03 | See third-party software **potentially outdated** | Yes | Compare product/edition/channel to approved Kaseya/manual catalog; never falsely call a missing patch |
| VSA-04 | See **actual pending third-party patch**, approval/deployment/failure/reboot state | Capability-gated | Only if documented supported VSA API/export for exact data is verified; otherwise display `API not available/verified` |
| VSA-05 | See OS missing/installed updates and per-device policy | Yes | `AvailableUpdates`, `InstalledUpdates`, `Updates`, `appliedpolicies` verified on live pilot |
| VSA-06 | See policy configuration (OS and SoftwareRules) | Yes | `GET /devices/{id}/appliedpolicies`, `GET /patchmanagement/policies/{id}`; distinguish policy setting vs execution outcome |
| VSA-07 | Upload expected device inventory Excel and compare onboarding | Yes | XLSX/CSV import, review mappings, classify every row, export results with reasons |
| VSA-08 | See group-level network info and member list | Yes | Group hierarchy + per-device interfaces/IP/MAC/mask/gateway/DNS; source freshness and duplicate IPs |
| VSA-09 | Find devices in incorrect group, missing expected grouping or stale/offline | Yes | Scoped searches and reconciliation reasons; no risky automatic modifications |
| VSA-10 | Move a device to another agent group | Phase P2W | Role restricted, preview, human approval, separate token, direct vendor write, verify and audit |
| VSA-11 | Bulk move multiple selected devices | Deferred, optional | Each device validated; batch preview/approval; no silent retries; explicit partial-success reporting |
| VSA-12 | Export device, patch, network, onboarding and movement reports | Yes (read); move reports when enabled | Excel/CSV/PDF, scoped to customer, as-of and source details |

## 1A. Additional high-value VSA inventory and investigation requirements

| ID | Function | Priority | Notes |
|---|---|---|---|
| VSA-13 | Devices with stale agents, old client versions, long-offline duration or no assigned patch policy | MVP | Distinguish inactive/offline from missing agent; group/customer trends |
| VSA-14 | Device hardware, disks and free-space/usage indicators | MVP | Use only source-reported `AssetInfo`, `Disks`, CPU/memory fields; snapshot and freshness required |
| VSA-15 | Security posture observations: reported antivirus, firewall, ransomware protection, UAC | P2 | Source states are evidence observations, not a security certification |
| VSA-16 | Notifications and basic device events | P2 | Supported `GET /devices/{id}/notifications` and event fields from documented device/asset API; separate monitoring from alerts |
| VSA-17 | Organization/site/group compliance overview | MVP | Counts, online/last seen, OS distribution, installed software, missing patch policy; always scoped |
| VSA-18 | Asset tags and custom fields | P2 | Read only through documented asset/device/group custom-field endpoints; customer-approved field allowlist |

Do not replace Kaseya VSA's native monitoring, patch engine, policy editing, agent deployment, or remote-control capabilities. Keep the portal focused on deep read-only investigation plus the single separately approved group-move action.

## 2. Device detail page — mandatory panels

1. **Overview:** VSA ID, hostname, organization, site, group (names and IDs), type, agent status/version, online/last seen, source URL and last sync.
2. **Operating system:** OS details, reboot/uptime if exposed, installed OS updates, available OS updates, severity where supplied; do not equate empty list with compliant when unscanned.
3. **Third-party applications:** product name/publisher/installed version, catalog match, reference version, comparison status, policy rule if present, catalog age, source evidence.
4. **Patch policies:** assigned Patch Management policy ID/name, OS rules, SoftwareRules and schedules from supported policy endpoint. Label configuration separately from observed outcomes.
5. **Network:** all reported adapters, IPv4/IPv6, MAC, subnet mask, derived CIDR where reliable, gateway, DNS, DHCP and public IP. Preserve multiple NICs.
6. **Asset identity:** serial number, asset tag, hardware fields if actually supplied, historical identities, Excel onboarding match, duplicate-candidate warnings.
7. **Group history and proposed move:** current hierarchy, proposed target and policy-impact warning, approvals and audit (available only to authorized roles).
8. **Data quality:** source timestamp, snapshot generation, stale/unknown/missing-API indicators and explicit no-data explanations.

**Distinguish** unobserved, stale, unsupported, source returned empty, failure, excluded and fully compliant states; do not turn missing fields into zeroes.

## 3. Third-party software and patch status — strict data semantics

There are three independent concepts:

| Term | Meaning | Minimum source |
|---|---|---|
| `installed_version` | Software reported installed by agent inventory | `/api/v3/assets` InstalledSoftware |
| `catalog_outdated` | An installed version compares below an explicitly matched reviewed reference version | Approved catalog (with timestamp, edition, architecture, release channel) |
| `third_party_patch_pending` | VSA reports a particular applicable third-party update is pending for the selected device | **Not proven from public `/assets` API alone**; gated until separately verified |

Never infer `third_party_patch_pending` from `catalog_outdated`; never infer a vulnerability solely from an old version. Do not falsely label `AvailableUpdates` as third-party patches: they are documented as **OS** updates. Inspect available VSA release-specific docs and the authorized tenant's `/api` reference. VSA UI **Patch Status** and **Patch Management > History** show more detail than the public asset API; that does **not** imply those details are available through a supported external API. VSA 10.25 introduced an Advanced Reporting Patch Summary dataset limited to one policy at a time; investigate only approved supported export/API paths, not scraping UI or unsupported SQL.

The UI should show `VSA third-party deployment status unavailable from configured connector` when no verified method exists; keep version-outdated reporting working.

## 4. Excel onboarding reconciliation — detailed contract

**Workflow:** Customer → Onboarding Comparison → Upload `.xlsx` or `.csv` → Select sheet/column mapping → Preview validation → Select a *completed* source snapshot → Run async comparison → Review exceptions → Export Excel/CSV/PDF → Save comparison version.

Columns mapping can include `Hostname`, `FQDN`, `SerialNumber`, `MAC`, `AssetTag`, `IP`, `ExpectedOrganization`, `ExpectedSite`, `ExpectedGroup`, `DeviceType`, `Notes`. Only hostname is required for a basic comparison; stronger identifiers improve precision. Validate total row count, duplicates, blanks, invalid values, sheet selection and header mapping. Reject macros (`.xlsm`), external formula execution and excessively large inputs. Read cell data without evaluating formulas.

**Normalization:** trim whitespace; canonicalize case and trailing DNS dots; hostname short-name vs FQDN matching only when domain scope is unambiguous; MAC separators removed/case canonicalized; serial and tag normalized without deleting meaningful characters; IP matching is weak/transient and never sufficient to silently identify a device. Never use fuzzy name similarity as a definitive match.

**Matching precedence:** within the *same mapped customer and VSA instance*, match exact approved source ID (if supplied); otherwise exact serial (only when unique), exact asset tag (unique and trusted), exact fully qualified hostname (unique), unique short hostname within validated site/domain scope, then MAC corroboration; conflicting signals are `ambiguous` and require review. A device reported in the wrong organization must not be silently matched across customers. Preserve match method, confidence, both raw values and operator override with audit.

**Classify every Excel row:**
- `onboarded_correct_group`: single confidently matched VSA asset, expected org/site/group match.
- `onboarded_wrong_group`: matched asset, group mismatch.
- `onboarded_wrong_site`: matched asset, site mismatch (validate target and permissions).
- `onboarded_wrong_org`: signal suggests outside approved customer scope; quarantine, never expose other customer data.
- `not_found_in_vsa`: no strong match in a **complete, recent** scoped snapshot; absence from VSA inventory is not proof agent never installed.
- `ambiguous_match`: more than one candidate or conflicting identities.
- `stale_or_offline`: matched but last seen beyond selected age threshold (secondary flag).
- `duplicate_excel_row`: repeated or conflicting source rows.
- `missing_required_key`: insufficient fields.

Also report `unexpected_vsa_asset`: devices present in VSA snapshot but absent from expected inventory. Display counts/percentages with explicit denominator (e.g., distinct valid expected rows) and show incomplete/stale snapshot warning; do not assert `not onboarded` unless source completeness is verified and wording qualified.

Suggested result columns: `ExcelRow`, `ExpectedHostname`, `ExpectedSerial`, `ExpectedSite`, `ExpectedGroup`, `FoundVsaIdentifier`, `FoundHostname`, `ActualSite`, `ActualGroup`, `LastSeen`, `Status`, `MatchReason`, `Confidence`, `SuggestedAction`, `ReviewedBy`.

**Security:** file size/row caps, temp file retention, anti-malware scan where available, parser timeout, customer ownership and per-file access control; audit upload/download/deletion; redact or reject sensitive columns not needed for reconciliation. Do not change VSA grouping from an Excel match automatically.

## 5. Groups and network overview

Group directory from `GET /api/v3/groups` + organization/site lookups, with source IDs, hierarchy, notes and members. Derived customer/group network view from asset/device interfaces:

- Group → devices → NICs/IPs/MACs/IPv4/IPv6, DHCP, DNS, gateway, subnet mask, public IP and reported state.
- Optionally derive CIDR from reported IPv4/netmask when valid, and summarize count of devices per subnet and duplicate IP/MAC collisions.
- Show a gap/quality score, last-seen timestamp, missing network data and multiple NICs.
- Network discovery/topology, switch-port, VLAN, DHCP scopes and authorized subnet inventory **are not inherently provided** by VSA group metadata; consider separate approved sources in a future integration.
- Use IPv4/IPv6 parsing libraries; do not assume every IP belongs to a management subnet or every MAC is globally unique (virtual/locally administered adapters exist).

## 6. Move device to another group — controlled operational workflow

VSA API officially documents `PUT /api/v3/devices/{deviceId}/move` with `{"GroupId": <integer>}`. This is a real **vendor-write** capability, not part of the default read-only connector.

**Authorization:** separate `vsa.group_move.propose`, `vsa.group_move.approve`, `vsa.group_move.execute` permissions; least privilege; no self-approval; require signed-in identity, MFA policy, change reference, reason, allowed customer scope, and a **separate write-capable credential** stored in vault. Enable only per approved VSA instance/customer through feature flags. Deny cross-customer moves and targets not validated as belonging to the same approved customer/instance. Same-customer cross-site moves may affect policies; show site/policy impact and require explicit authorization.

**Operator flow:**
1. Engineer finds a device and clicks **Propose Move**.
2. Portal fetches fresh `GET /api/v3/devices/{id}`, `GET /api/v3/groups`, and assigned policy information.
3. User selects target group from a filtered, authorized list and supplies reason/change reference.
4. Portal shows **Before → After** hierarchy, applied policy-change risk, device identity and request expiry.
5. A different authorized approver reviews exact immutable proposal; current state must be revalidated before execution.
6. Authorized executor sends **one** vendor `PUT` and records the attempt + correlation ID before execution.
7. Portal reads device again, verifies target GroupId and records success, failure or **unknown outcome**.
8. For timeout/uncertain response: **never blindly retry**. Re-read authoritative VSA state first and request manual resolution if still uncertain.
9. Write immutable portal audit, optional upstream ticket reference, and update reporting snapshot/sync.

Implement one-device move first. Batch moves only after per-item validation and safe partial-result semantics. No routine patch execution, policy edits, device deletion, remote shell, reboot, credential retrieval or agent deployment.

**Failure cases:** target deleted/renamed, device moved by another operator, source snapshot stale, device belongs to different organization/customer, permission revoked, vendor 403/429, timed-out write, policy impact changes, DR/VSA unreachable. Every case must fail closed or show an explicit `unknown` result and require review.

## 7. Source and endpoint capability register

| API / source | Purpose | Status |
|---|---|---|
| `GET /api/v3/assets` | InstalledSoftware, OS `AvailableUpdates`, IP interfaces, inventory | Verified public docs; live pilot pending |
| `GET /api/v3/assets/{id}` | Device inventory, OS `InstalledUpdates` by include | Verified public docs; live pilot pending |
| `GET /api/v3/devices/{id}` | Device, online/group/agent and rich NIC details | Verified public docs; live pilot pending |
| `GET /api/v3/groups` | Group IDs, names and org/site hierarchy | Verified public docs; live pilot pending |
| `GET /api/v3/devices/{id}/appliedpolicies` | Associated policies | Verified public docs; live pilot pending |
| `GET /api/v3/patchmanagement/policies/{id}` | Patch policy configuration, OS/SoftwareRules | Verified public docs; live pilot pending |
| `PUT /api/v3/devices/{id}/move` | Group move | Verified public docs; must remain disabled until security approval |
| Patch History / Patch Status UI | Actual pending/failed/reboot/deployed states | UI documented; *external data API availability unverified* |
| VSA Advanced Reporting Patch Summary | Policy-scoped patch summary | 10.25+ product feature; supported machine API/export method not yet validated |

Official references:
- <https://api.vsax.net/>
- <https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/patch-review.htm>
- <https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/history.htm>
- <https://help.vsa10.kaseya.com/help/Content/0-Home/release-notes/2026/10.25.htm>
- <https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm>

## 8. Backend entities (add to DATABASE.md implementation)

- `ExpectedInventoryImport` (customer, uploader, file hash, sheet/column mapping, created/expiry, encrypted artifact reference).
- `ExpectedInventoryRow` (import, row number, raw normalized keys, expected hierarchy, validation status).
- `InventoryReconciliationRun` (customer, import, VSA integration, snapshot generation, result counts, as-of and currentness).
- `InventoryReconciliationResult` (run, expected row, VSA asset if matched, status, confidence, reason, operator review).
- `GroupNetworkSnapshot` / `AssetNetworkInterface` (source group, device, IP/MAC/mask/gateway/DNS/DHCP, as-of; avoid redundant data where interface model suffices).
- `DeviceAppliedPolicy` / `PatchPolicyObservation` (policy assignments, policy settings, version/as-of).
- `VsaWriteCredentialReference` (vault reference only; separate from read credential).
- `DeviceGroupMoveRequest` (customer, instance, device ID, original group, target group, reason, change ref, immutable diff hash, status/expiry).
- `DeviceGroupMoveApproval` (request, independent approver, decision, timestamp, evidence).
- `DeviceGroupMoveExecution` (request, attempt ID, actor, vendor response metadata, verification state, timestamps and audit correlation).

## 9. Application API targets (internal only; authenticated, scoped)

- `POST /api/v1/customers/{id}/onboarding-imports/` (file upload and validation preview)
- `POST /api/v1/customers/{id}/reconciliations/` (async compare to pinned successful VSA snapshot)
- `GET /api/v1/customers/{id}/reconciliations/{run}/results/`
- `GET /api/v1/customers/{id}/groups/{group_id}/network/`
- `GET /api/v1/customers/{id}/assets/{asset_id}/patches/`
- `GET /api/v1/customers/{id}/assets/{asset_id}/software/`
- `POST /api/v1/customers/{id}/devices/{device_id}/move-proposals/` (disabled until P2W approval)
- `POST /api/v1/move-proposals/{proposal_id}/approve/` (independent approval)
- `POST /api/v1/move-proposals/{proposal_id}/execute/` (separate permission, idempotency guard, revalidation)

All endpoints are **targets to implement**, not existing portal APIs.

## 10. Acceptance scenarios (must become automated tests)

1. Upload 100 expected Excel assets; 80 exact matches, 10 no matches, 5 wrong group, 3 ambiguous, 2 duplicate rows; export reproduces every classification and totals.
2. Duplicate hostname exists in two customer organizations; no cross-customer match or information leak.
3. Asset is missing from an incomplete VSA sync; never report definitively unonboarded.
4. Same device has two NICs on two subnets; both appear on device and group network views, with correct mask-to-CIDR calculations.
5. Third-party outdated version is reported as `catalog_outdated`; without documented applicability feed, `third_party_patch_pending` remains `unverified`.
6. VSA policy `SoftwareRules` says update a product; UI labels that as a **policy rule**, not a deployment result.
7. A Viewer cannot propose/approve/execute a move; proposer cannot approve own move; cross-customer target is blocked.
8. Vendor move API returns timeout after write: read-back resolves success when group matches; otherwise leave `unknown` and do not repeat PUT.
9. Approval is revoked or device's original group changes before execution: proposal becomes invalid; no PUT sent.
10. Report based on old Excel upload or catalog snapshot remains reproducible, with source/compare metadata.

## 10A. Further investigation tests

- Device reports `FirewallEnabled = false` or antivirus unknown; show the actual state and source timestamp without inventing a vulnerability.
- Disk and CPU statistics are stale relative to the asset list; show the telemetry age and do not present them as live performance.
- Device has no applied Patch Management policy; report `No Patch Policy` instead of `Fully Patched` even if no updates are returned.
- A device is offline but still onboarded in VSA: Excel comparison marks it matched/onboarded with an offline secondary flag, never missing.
- Custom-field values potentially contain sensitive data; only fields on the approved allowlist may be synchronized and exported.

## 11. Priority and delivery gates

- **MVP A (P0 + P1):** Auth/RBAC, complete VSA device and installed software inventory, source policies, device details, **Excel onboarding comparison**, **group network view**, software-version compliance, scoped CSV/Excel exports. No vendor writes.
- **P2:** OS patch reporting and report engine, expanded patch capability discovery; only evidence-backed third-party deployment state may be enabled.
- **P2W optional controlled actions:** One-device VSA move with approvals, separate vendor token, live tenant acceptance and security sign-off. Must never block read-only MVP.
- **P3/P4:** IT Glue and Autotask PSA as originally planned.
- **P5:** Production hardening, auth, secrets, backups, performance and controlled pilot.
- **Future:** Approved optional MCP interface using the same scoped services, no direct vendor access bypass.
