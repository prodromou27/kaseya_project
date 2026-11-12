# Vendor API integrations and capability register

**Document review date:** 2026-11-12. **Status:** Public documentation reviewed; **no live tenant credentials or test results**. Every connector must be fixture-tested and then pilot-validated before marked operational.

## 1. Adapter contract

Create a typed `BaseReadOnlyAdapter` interface:

```python
class ReadOnlyAdapter(Protocol):
    def connection_check(self) -> ConnectionHealth: ...
    def list_source_organizations(self) -> Iterable[ExternalOrganization]: ...
    def collect_dataset(self, mapping: ApprovedCustomerMapping, checkpoint: SyncCheckpoint | None) -> Iterator[SourceRecordPage]: ...
    def normalize_record(self, item: dict) -> NormalizedRecord: ...
```

Implement source-specific methods in separate modules; do **not** force unrelated vendor entities into one false common schema. Never expose raw credentials in results or logs. All vendor HTTP calls use `GET` for this release (unless the vendor's documented read-only query operation requires a POST; approve that individual exception explicitly and ensure it has no side effect). Maintain a **default-deny endpoint allowlist**. Auth errors must stop retries; 429 respects `Retry-After`; 5xx/timeouts get bounded retry and checkpointing. Keep full URL allowlisted per integration instance and block SSRF/private redirect paths except approved VSA internal addresses.

## 2. Kaseya VSA X (VSA 10)

**Official reference:** <https://api.vsax.net/>

**Confirmed public documentation:**
- Uses HTTP **Basic Authentication** of `TOKEN_ID:TOKEN_SECRET` (Base64) over **HTTPS**.
- List assets: `GET https://<server_name>/api/v3/assets`.
- Get one asset: `GET https://<server_name>/api/v3/assets/:id`.
- List page controls: `$top` (max 100, default 100) and `$skip`, plus documented `$filter`, `$orderby`, `include`.
- The list asset response has `Data` and metadata including `Meta.TotalCount` in official examples; validate actual payload shape per product release.
- `InstalledSoftware` entries include `Name`, `Publisher`, `Version`.
- `AvailableUpdates` = **available OS updates**, `InstalledUpdates` = **installed OS updates**, and `Updates` = OS update counts.
- The list endpoint defaults to `InstalledSoftware` and other sections; `InstalledUpdates` on the specific-device endpoint requires explicit `include` when used.
- Typical documented per-token/per-endpoint limit is 3,600 requests/hour; limits are sliding-window and 429 includes `Retry-After`. Respect actual response headers and admin policy, not just nominal limit.

**Example (placeholders only):**

```bash
curl --fail --silent --show-error \
  --user "${VSA_TOKEN_ID}:${VSA_TOKEN_SECRET}" \
  --get 'https://vsa.example.internal/api/v3/assets' \
  --data-urlencode '$top=100' \
  --data-urlencode '$skip=0' \
  --data-urlencode 'include=InstalledSoftware,AvailableUpdates,AssetInfo'
```

**Implementation notes:**
1. Implement paginated `GET /api/v3/assets` with a fixed server-side page size ≤100; test full pagination and count inconsistencies.
2. Validate `OrganizationId`, `SiteId`, `Identifier`, `Name`, `GroupName`, `LastSeenOnline` and `InstalledSoftware`. Site and group names can change; source IDs must be primary keys.
3. Use `GET /api/v3/assets/:id` only for fields missing from list and prioritize API budget. Never assume every record has all nested arrays.
4. Create per-instance throttling and documented retry handling. A schedule for a large estate must be derived from observed request counts.
5. Document and test OData filter escaping if filters are used; never concatenate unchecked user input into filter expressions.

**Third-party patch applicability is not confirmed:** `InstalledSoftware` + reference catalog supports only **version comparison**. Do **not** label this as actual pending third-party patch deployments or verified vulnerabilities. Public documentation reviewed here does not establish a general per-device third-party missing-patch feed. Investigation of other official APIs must produce an evidence-backed capability record before feature activation.

### 2.1 Implementation status (2026-11-12, commit `23550d1`)

* Implemented: `GET /api/v3/assets` (per approved org, `$top=100`, `$skip`, `$filter=OrganizationId eq <int>`,
  `$orderby=Identifier`, `include=Tags,AssetInfo,InstalledSoftware`) and `GET /api/v3/organizations` (admin discovery).
  Evidence record: `backend/apps/integrations/vsa/capabilities.json`.
* **Fixture-tested only.** No live tenant has been called. Live pilot pending DEC-04/DEC-10.
* Credentials: `credential_ref = env:NAME`, where `NAME` (or `NAME_FILE`) holds `TOKEN_ID:TOKEN_SECRET`. Vault support is P5-02.
* Since P2 (commit `c483a8f`): `include` also requests `Updates,AvailableUpdates`. `GET /api/v3/assets/:id?include=InstalledUpdates`
  is called per device within `installed_updates_budget` (default 0 = off). `InstalledAt` is stored verbatim (no timezone documented).
  There is no documented scan timestamp. All of this is fixture-tested only.
* Residual risk: `$skip` paging cannot detect equal numbers of inserts and deletes between pages (see ADR-019).

## 3. IT Glue

**Official reference:** <https://api.itglue.com/developer>

**Confirmed public documentation:**
- HTTPS REST API using **JSON:API** response structure (`data`, `attributes`, `relationships`).
- Header `x-api-key: <token>`; `Content-Type: application/vnd.api+json` for requests with payload.
- Regional API base URLs include `https://api.itglue.com`, `https://api.eu.itglue.com`, and `https://api.au.itglue.com`.
- `GET /organizations` and `GET /configurations` and the documented organization-specific configuration relationship endpoint are available.
- Pagination uses `page[number]`, `page[size]` (documented upper bound 1,000 records/page), sorting/filtering per endpoint; honor actual pagination links when present.
- Public documentation lists a rate limit of up to **3,000 requests in a five-minute window**, returning 429 on throttling.

**Read-only integration scope:** organization metadata, configurations, configuration types, statuses, manufacturers, models, and limited configuration interfaces. **Explicitly forbidden:** passwords, secrets, flexible-asset content of unapproved sensitivity, secure notes, attachments, sensitive raw notes, third-party credential replication.

**Identity correlation:** IT Glue `organization-id` -> approved `customer_source_mapping`; device configuration to VSA asset using reviewed serial number/hostname/ID correlation. Preserve unlinked/ambiguous statuses and manual review.

**Example (never commit a real key):**

```bash
curl --fail --silent --show-error \
  -H "x-api-key: ${ITGLUE_API_KEY}" \
  'https://api.eu.itglue.com/organizations?page[size]=100&page[number]=1'
```

## 4. Autotask PSA

**Official docs:** <https://www.autotask.net/help/DeveloperHelp/>

**Confirmed public documentation:**
- Use an API-only user and API integration/tracking identifier.
- Request headers `UserName`, `Secret`, and `ApiIntegrationCode` (case shown in vendor examples).
- Autotask operates multiple geographic **zones**. Query the documented `zoneInformation` endpoint for the API-only username to select the correct `https://webservicesN.autotask.net/atservicesrest` base URL. **Zone discovery is not credential validation**.
- Available entities include **Companies** and **Tickets**. Confirm exact route/query syntax against the API schema and the customer's zone before implementing.
- The official API guidance states entity query responses are capped at **500 records per call**; implement repeatable paging/ID cursor traversal following current documentation and source behavior.
- The default API User security level can expose wide data including internal costs. Use a **copied, restricted API security level**, with minimum applicable company/ticket access; never retrieve costs, billing, sensitive UDFs, or other unrelated entities.

**Connector responsibilities:** retrieve companies and approved ticket fields, map company IDs to internal customers, track statuses/priorities and dates, compute ticket statistics using explicitly defined rules. Ticket-to-device matching is optional and must be evidence-backed. Avoid storing ticket bodies by default; titles can also contain sensitive information, so sanitize and restrict as needed.

**Example header shape (example only; route is intentionally not assumed):**

```text
UserName: <api-user>
Secret: <api-secret>
ApiIntegrationCode: <tracking-id>
Content-Type: application/json
```

**Approval gate:** Before enabling production ingestion, confirm exact company/ticket field permissions, zone, paging, sensitive UDF handling, and customer-scoped extraction capability in a live test tenant or approved customer scope.

## 5. Capability matrix

| Desired data | Source | Public documentation evidence | Implementation posture |
|---|---|---|---|
| Devices, org/site/group, last seen | VSA X | `GET /api/v3/assets` | P1, fixture then live test |
| Installed third-party software versions | VSA X | `InstalledSoftware` field | P1, version inventory only |
| Available OS updates | VSA X | `AvailableUpdates` field | P2, source freshness required |
| Installed OS updates | VSA X | `InstalledUpdates` on specific asset | P2, API budget check |
| Patch failure history | VSA X | **Not established from reviewed asset endpoint** | Not available until verified |
| Third-party per-device missing patches | VSA X | **Not established in reviewed public docs** | Do not claim; optional future investigation |
| Organizations and configurations | IT Glue | `GET /organizations`, `/configurations` | P3, allowlist safe fields |
| Companies and tickets | Autotask PSA | REST entity docs, zone-specific routing | P4, confirm query syntax |
| Vendor-specific live vulnerability closure | None in v1 | Tenable not integrated | Out of scope |

## 6. Required adapter fixtures and tests

For every provider, store **synthetic or sanitized** example JSON under `backend/tests/fixtures/<provider>/`. Test empty pages, malformed pages, rate limits, auth denial, duplicate IDs, missing fields, pagination boundaries, disabled customer mappings, stale timestamps, and changes between API versions. Add a `capabilities.json` per adapter documenting every field's verified origin. Fixture tests are not live proof.

## 7. No-live-credentials behavior

Without credentials, connectors must remain **disabled**. The portal may run with clearly marked fictional demo data. Admins see `not_configured` and an explicit action list. Never include fabricated sample data in reports presented as production facts.

## 8. Documentation links

- VSA: <https://api.vsax.net/>
- IT Glue: <https://api.itglue.com/developer>
- Autotask authentication: <https://www.autotask.net/help/DeveloperHelp/Content/APIs/REST/General_Topics/REST_Security_Auth.htm>
- Autotask API best practices: <https://www.autotask.net/help/developerhelp/content/apis/REST/General_Topics/REST_BestPractices.htm>
- Autotask zone discovery: <https://www.autotask.net/help/developerhelp/content/apis/REST/API_Calls/REST_ZoneInformation.htm>
