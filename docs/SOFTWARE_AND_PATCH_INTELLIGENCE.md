# Software versions, third-party patch capability and Windows updates

## Concept separation (non-negotiable)

| Statement | Required evidence | UI label |
|---|---|---|
| Software is installed | VSA `InstalledSoftware` observation with version | Installed software |
| Installed version is behind reviewed reference | compatible product, edition, channel & architecture catalog revision | **Outdated version** |
| Third-party patch is applicable | documented and tested VSA patch applicability source | **Applicable third-party update** |
| Third-party patch is pending/failed/reboot/deployed | explicit VSA state from supported route/export | **Deployment status** |
| Windows OS update available/installed | VSA `AvailableUpdates` / `InstalledUpdates` | **Windows OS patch status** |
| Device is vulnerable | authoritative vulnerability evidence from an approved future source | **Not in Phase 1** |

No inference across rows. Native VSA web UI states are not automatically externally available. A policy `SoftwareRules` entry means a policy configuration; it does not establish installation or deployment.

## Software inventory and reference catalog

Capture raw product/publisher/version and normalized reviewed product, channel, edition and architecture. Use compatible references only. Store source URL, release date if evidenced, catalog revision, reviewer, last refreshed and reconciliation reason. Unknown product aliases stay `UNKNOWN`, not guessed. Allow admin-approved CSV/XLSX manual catalog import; no arbitrary external website scraping. No latest-version claim without independently verified source and timestamp.

### Classification

- `CURRENT`: equal versions under product-specific comparator.
- `OUTDATED`: reliably lower version under same compatible release line.
- `NEWER_THAN_REFERENCE`: reliably higher than reference.
- `UNKNOWN`: no matching reference or unparsable version/ambiguity.
- `UNSUPPORTED`: lifecycle catalog says unsupported with source citation and date.
- `EXCLUDED`: governed exception with owner, reason and expiry.

Version rules must handle numeric dotted Windows builds, suffixes, ESR/LTS, enterprise channels, beta and product-specific schemes; don't use generic SemVer alone. Unit test comparators.

## OS patch/policy views

Use `AvailableUpdates` and `InstalledUpdates` with page/snapshot as-of; count only items matching verified schema. Show KB/title/severity/source status where fields exist. For `appliedpolicies`, display `Patch Management` policy, `No Policy` explicit, unknown and fetch error separately. Retrieve policy definitions via documented patch-management policy endpoint and label as configuration. Compare to administrator-reviewed expected group policy (drift) without modifying VSA.

### Metrics

- `version_outdated_device_rate = distinct eligible devices with >=1 OUTDATED installation / distinct eligible inventory devices`, with unknown/stale excluded or separately reported.
- `OS updates available devices = distinct eligible devices with >=1 documented available OS update`, not automatically a failed deployment.
- `patch policy coverage = devices with known applicable patch policy / eligible devices with verified assignment state` plus unknown/unscanned counts.
- Never report 100% compliance when scan freshness, catalog coverage or policy data is unknown.

## Pending third-party patch research gate

1. Investigate the VSA version, API route availability, permissions and Advanced Reporting Patch Summary (VSA 10.25+, one policy per report).
2. Determine **supported machine-consumable** API/export and mapped device-level status (if any).
3. Confirm applicability, approval, target version, deployment pending, failed, success, reboot pending with sanitized pilot evidence.
4. Add adapter capability bit and source provenance; only then enable the status view.
5. If not supported, display: `Pending third-party patch status is not available from the configured VSA API; installed version comparison is shown separately.`

## Reports

Software by product/device/customer; outdated version trend; unknown catalog coverage; Windows updates by KB/device/group; policy coverage and drift; failed deployment **only with verified external data**; lifecycle reference sources and end dates.

## Implementation notes — lifecycle catalog (VSA4-05, fixture-tested only)

* **Entry:** an OS family as reported (e.g. `Windows 11`) or a reviewed catalog product, a release label, an optional
  dotted version prefix (component-wise: `10.0.22631` matches `10.0.22631.4317`, not `10.0.2263`), end of support,
  optional mainstream end / extended (ESU) end, an https source URL, the date it was checked, and a confidence.
* **Review:** proposed by one super admin, approved or rejected by a different one; approved entries cannot be edited
  or deleted (DB trigger), only retired.
* **Classification** (as of a date): `end_of_support`, `ending_soon` (within 180 days), `supported`, or `unknown`.
  Only approved entries with *official* confidence classify. The most specific match wins (longest OS family, then
  longest version prefix); equally specific entries with different dates give `unknown` (`conflicting_entries`).
  Unknown reasons: no entry, unverified source only, conflicting entries, OS not reported, unparsable version,
  software not matched to a reviewed product.
* **Naming:** the software comparison state `unsupported` keeps its API value but is labelled **Not catalogued**; it
  means "no reviewed product", not "past end of support". Lifecycle uses its own statuses.
* **Report R17** (`lifecycle`) pins the snapshot, software evaluation, evaluation date and exact entry IDs, so a
  regenerated report is identical even after an entry is retired.
* **No vendor dates are shipped.** The demo seed creates illustrative `(DEMO)` entries with a `.invalid` source.

## Implementation notes — applied patch policies (VSA3-04, `ff7a956`, fixture-tested only)

* **Sources:** `GET /api/v3/devices/:id/appliedpolicies` (per device, `$top` at most 100, documented 3600 requests/hour)
  and `GET /api/v3/patchmanagement/policies/:id`. Both were verified in the public docs on 2026-11-13; live validation
  is pending.
* **Budget:** per-device calls are limited by `applied_policies_budget` on the integration (default 0, so off).
  Never-collected devices go first, then the least recently collected. A device not fetched in a run carries forward
  its last response, with the original response time shown.
* **States per device:**
  * `assigned`;
  * `explicit_none`: the documented `PolicyId: null`, "No Policy (Explicitly configured)" rule;
  * `not_reported`: the response had no Patch Management entry;
  * `unknown`: not collected or failed.

  `not_reported` and `unknown` are never counted as "no policy".
* **Coverage** = assigned ÷ (assigned + explicit_none). Excluded unknown and not-reported devices are shown next to the
  percentage.
* **Definitions** are stored as *configuration*:
  * kept: Name, Description, the documented `GeneralSettings` keys, `OsRules`, and `SoftwareRules`
    (ProductId/ProductName/Action);
  * dropped: `NotificationSettings` and profile `Settings`.

  A content hash flags a definition that changed since the previous sync. None of this is deployment evidence.
* **Drift** compares against a reviewed baseline at organisation, site or group scope; the most specific scope wins. A
  customer administrator proposes it, and a *different* administrator approves it. Proposals never affect drift.
  States: `matches`, `different_policy`, `missing_policy`, `unexpected_policy`, `unknown`, `no_baseline`.
* **Report R08** (`patch_policy_coverage`) is pinned to the generation. Drift uses the expectations approved at
  generation time.
