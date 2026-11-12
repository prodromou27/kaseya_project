# VSA source/normalized data dictionary and semantics

The following names are **internal canonical model concepts**, not claims of exact VSA JSON keys. Derive actual JSON mapping from documented responses and the live validation log. Store raw source identifiers and both `source_observed_at` (if provided) and `synced_at`.

| Canonical item | Key requirements | Notes |
|---|---|---|
| Customer | uuid, name, code, enabled | internal, not VSA org display name |
| VsaInstance | uuid, approved HTTPS base_url, version, credential refs, enabled | rate budgets and TLS policy |
| CustomerVsaScope | customer, instance, external org ID(s), review evidence | explicit mapping; quarantine unmatched |
| VsaOrganization/Site/Group | source ID, source parent ID, names, instance, generation | hierarchy belongs to instance |
| Device | `(instance_id, vendor_device_id)`, mapped customer, current generation | never use IP or hostname as PK |
| DeviceObservation | source/os/agent/online/last_seen, timestamps, raw subset | immutable generation |
| DeviceNetworkInterface | per NIC identifier, MAC, IP list, mask, gateway, DNS, DHCP when present | multi-NIC and IPv6; avoid conflating public IP |
| DiskObservation | device, volume, capacity, free%/bytes, timestamp | source units must be validated |
| SecurityObservation | observed AV/firewall/UAC/ransomware attributes, tri-state | NOT a security certification |
| SoftwareProduct | normalized name, publisher, edition/channel/architecture | alias mappings reviewed |
| SoftwareInstallObservation | device, source product/version, detection time, generation | no install date inference |
| ReferenceCatalogRevision | product/edition/channel, version, source, reviewed_by, as-of | immutable revisions |
| VersionClassification | installation, catalog revision, state/reason, calc version | `outdated` != `pending patch` |
| OsUpdateObservation | device, KB, title, severity/type/status when present | available vs installed; OS only |
| AppliedPolicyObservation | device, type, policy ID/name, source time | `No Policy` explicit vs missing response |
| PolicyDefinitionObservation | policy snapshot, rules, settings, version/time | config, not execution result |
| NotificationObservation | event source ID/type/message/time | control sensitive source text |
| SyncGeneration/Run | instance, scope, started/completed, coverage counts, publish state | incomplete never replaces last valid |
| ExpectedInventoryUpload/Row | owner, customer, sheet/map, original/normalized identifiers | encrypted TTL, size limits |
| ReconciliationRun/Result | upload+source generation, match class, evidence and review | historical reproducibility |
| MoveRequest/Approval/Execution | immutable expected source/target, approver, attempt and readback | separate feature flag and write token |
| ReportRun/Artifact | customer/snapshot/filter/calc versions/content hash, private path | expiring authenticated downloads |

## Shared status vocabulary

- `KNOWN_PRESENT`, `KNOWN_ABSENT`, `UNKNOWN`, `NOT_COLLECTED`, `UNSUPPORTED`, `STALE`, `SOURCE_ERROR` are **not interchangeable**.
- A missing list on a failed/incomplete import cannot be counted as `0`.
- `DEVICE_ONBOARDED` means matched in a valid VSA inventory at the reported as-of time; it does not guarantee agent health.
- `VERSION_OUTDATED` is a catalog comparison; `OS_UPDATE_AVAILABLE` is VSA OS update observation; `THIRD_PARTY_PATCH_PENDING` is only true from a verified applicability/deployment source.
- `PATCH_POLICY_PRESENT` and `PATCH_DEPLOYMENT_SUCCEEDED` are independent facts.
- A device absent from two complete inventories may be an inferred removed device, not vendor-confirmed deletion.
- For month comparison, preserve dataset cut-off and catalog revision so historical results are reproducible.

## Multi-customer security

All customer-owned rows use `customer_id` (not merely instance ID) except explicitly global reference catalog. Enforce scoping in database query services, task payloads, search, exports, and file downloads. Source IDs are namespaced by integration instance. Never associate an unreviewed external organization with an internal customer automatically.
