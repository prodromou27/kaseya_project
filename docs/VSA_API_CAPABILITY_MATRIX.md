# Kaseya VSA X REST API — capability matrix

## Remediation verification — 2026-11-14

The public reference at https://api.vsax.net/ was re-opened during the Codex audit. The help-site root returned HTTP 404 through the research tool. No installed tenant/version was accessed and no new live vendor request was made. Existing route/field fixtures were rerun in the complete **585-test PostgreSQL suite**; this is fixture validation, not new live evidence.

| Remediation feature | Documented vendor capability | Implemented | Fixture-tested | Live-tested by this run | Limitation |
|---|---|---|---|---|---|
| Current dashboard and filtered inventory/software/update drilldowns | Existing read-only normalized source data | Yes | Yes | No | Current customer aggregate; historical trend points are separate |
| Group-network CSV/XLSX/PDF (R10) | Existing reported adapter/IP/mask/gateway/DNS observations | Yes | All three formats, source/customer scope and absent sections | No | Derived CIDRs are not topology discovery |
| Group move proposal/review | Internal portal CRUD; no vendor endpoint used | Yes | Independent approval, expiry, immutable source/destination and tenant denial | No | No execution route, write credentials or vendor readback |
| Third-party patch applicability/deployment | Not established for the configured integration | No | Explicit unavailable UI retained | No | Version-outdated is separate from pending/deployed patch |
| Failed-update/reboot state | Requires authoritative field/capability verification | No | Unavailable states retained | No | No state is inferred from KB inventory |

This update does not promote any route below to live-verified or authorize a VSA write. Full results and external gates: CODEX_VERIFICATION.md.

**Public documentation checked:** 2026-11-12; **source** <https://api.vsax.net/>.  
**Installed tenant/version:** unknown until pilot. **Live test status:** `PENDING` for every route below.  
**Current public help release as checked:** VSA 10.29 (<https://help.vsa10.kaseya.com/help/Content/0-Home/release-notes/2026/10.29.htm>); do not assume customer on-prem VSA is on that release.

`DOCUMENTED` below means documented publicly, **not tested on your tenant**. Verify exact fields, permissions and paging in the installed build. Public docs show API v3 BASIC auth using token ID + token secret over HTTPS. The API has per-token/endpoint and failed-request rate limits, with `Retry-After` on 429. Avoid relying on any fixed hourly limit across versions.

| Capability | Documented route or source | Status | Phase 1 treatment |
|---|---|---|---|
| Connection/rate budget | `GET /api/v3/ratelimits` | DOCUMENTED | test & monitor |
| Device list/detail | `GET /api/v3/devices`, `GET /api/v3/devices/{id}` | DOCUMENTED | mandatory |
| Device assets | `GET /api/v3/assets`, `GET /api/v3/assets/{id}` | DOCUMENTED | mandatory, validate asset/device ID relationship |
| Software installed | `InstalledSoftware` in asset include sections | DOCUMENTED | version inventory only |
| Available **OS** updates | `AvailableUpdates` asset include | DOCUMENTED | do not call third-party patches |
| Installed **OS** updates | `InstalledUpdates` on asset detail | DOCUMENTED | verify appropriate `include` |
| OS update severity counts | `Updates` asset include | DOCUMENTED | only with known semantics |
| Network & disks | `IpAddresses`, `LocalIpAddresses`, `Disks`, device NIC fields | DOCUMENTED | group aggregation; no topology claims |
| Reported security fields | `Security` asset include | DOCUMENTED | observations, not an audit opinion |
| Organizations | `GET /api/v3/organizations` | DOCUMENTED | mandatory mapping |
| Sites | `GET /api/v3/sites` | DOCUMENTED | mandatory |
| Groups | `GET /api/v3/groups` | DOCUMENTED | mandatory |
| Applied policies | `GET /api/v3/devices/{id}/appliedpolicies` | DOCUMENTED | config, not execution |
| Patch policy details | `GET /api/v3/patchmanagement/policies/{id}` | DOCUMENTED | OS/SoftwareRules verify per version |
| Device notifications | `GET /api/v3/devices/{id}/notifications` | DOCUMENTED | read only |
| Antivirus details | `GET /api/v3/devices/{id}/antivirus` | DOCUMENTED | read only |
| Device custom fields | `GET /api/v3/devices/{id}/customfields` | DOCUMENTED | allowlist only |
| Audit entries | `GET /api/v3/auditlogs` (confirm route against live docs) | REQUIRES_VALIDATION | source audit correlation |
| Move one device | `PUT /api/v3/devices/{deviceId}/move` with `GroupId` | DOCUMENTED_WRITE | **disabled by default**; separately approved |
| Third-party applicable/pending update per device | Not established from asset include fields | **UNVERIFIED** | show `UNAVAILABLE` until valid source proven |
| Failed/reboot-pending third-party deployment | UI statuses do not establish public API | **UNVERIFIED** | no inferred status |
| Advanced Reporting Patch Summary | VSA 10.25+ report dataset, **one policy at a time** | PRODUCT_FEATURE | evaluate supported export/API; no screen scraping |
| Advanced Reporting site maps/discovered devices | VSA 10.26+, **one site map at a time** | PRODUCT_FEATURE | optional if supported machine retrieval exists |
| Software catalog latest version feed | VSA application catalog documented as a feature; direct feed not established | **UNVERIFIED** | reviewed reference catalog CSV/XLSX required |

**Investigation workflow:** obtain VSA version → select read-only pilot org → check token permissions → test endpoints (minimal pages, redacted output) → record response fields & timestamps → record exact status code/pagination/rate headers → fixture from sanitized output → mark `LIVE_VERIFIED`. Never put credentials, real hostnames or personal data into docs/commits.

## Capability register file to maintain

For each route create a row in `docs/VSA_LIVE_VALIDATION_LOG.md`: source, date, tenant version, permission scope, request parameters (no token), status, observed fields, pagination, `supported/partial/unavailable`, source code test/fixture, reviewer. *Do not fill live results until truly tested.*

## Reference links

- <https://api.vsax.net/>
- <https://help.vsa10.kaseya.com/help/Content/0-Home/release-notes/2026/10.25.htm> (Patch Summary reporting)
- <https://help.vsa10.kaseya.com/help/Content/0-Home/release-notes/2026/10.26.htm> (site maps reporting)
- <https://help.vsa10.kaseya.com/help/Content/0-Home/release-notes/2026/10.29.htm> (current public release when reviewed)
- <https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm>
