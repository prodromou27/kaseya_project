# VSA X custom field assignment — implementation plan and API findings (CFA)

Status: implemented in stages CFA-01 to CFA-09 (see `TASKS.md`). Writes are **off by default** and stay off until the route has been validated on an authorised test workstation (section 5).

## 1. What exists already (CFA-01 audit, 2026-11-18)

| Area | Existing | Reused |
|---|---|---|
| Read of device custom fields | `GET /api/v3/devices/{id}/customfields` during sync, values kept only for names a customer approved (`CustomFieldAllowlist`, VSA-18); credential-like names can never be approved (`is_sensitive_field_name`) | Same read route for the preview; the same name guard refuses portal-writable status for credential-like fields |
| Scope custom fields | `GET /{organizations,sites,groups}/{id}/customfields` (CF-02) | — |
| Vendor write | One gated write: group move `PUT /devices/{id}/move` (ADR-029): server switch + integration switch + separate `env:VSA_WRITE_*` token, one attempt, read-back | Same pattern, same separate write token |
| Inventory | Current snapshot per customer: hostname, domain, serial, site, group, device type, server marking (SRV-01) | Matching engine, workstation-only rule |
| Upload parsing | Hardened CSV/XLSX importer (macro/zip-bomb/DTD refusal, formulas never evaluated) | CSV/XLSX import |
| RBAC | Code-defined roles: super admin, customer admin, engineer, viewer | Three new capabilities (section 6) |
| Exports | Formula neutralisation (`neutralize_cell`), string-only XLSX cells | Job report |

## 2. API findings (https://api.vsax.net/, read 2026-11-18; no live call made)

| Operation | Verb and documented route | Notes |
|---|---|---|
| List definitions | `GET /api/v3/customFields` (`$top` ≤ 100, `$skip`, `$filter`, `$orderby`) | `Id, Name, Description, Type (Text/Number/Date/Boolean), DefaultValue, GlobalValue, IsReadOnly, Contexts (Global/Organization/Site/Group/Device), ExpirationDate, CreatedAt`. The table calls the property `Context`, the example `Contexts`: both are read. |
| One definition | `GET /api/v3/customfields/{id}` | Same fields |
| Where a field is used | `GET /api/v3/customfields/{id}/usage` | `UsageContextType, ContextItemId, Value`; filterable on all three (`$filter=UsageContextType eq 'Device' and ContextItemId eq '<guid>'`). **This is how the portal tells an explicit device-level assignment from an inherited value.** Items the token cannot see are omitted. |
| Device values | `GET /api/v3/devices/{id}/customfields` | `Id, Name, Value, Type`, filterable by `Id`. The documentation does not say whether inherited values are included; it is shown as "effective value" only. |
| Assign | `POST …/customfields/{id}/assign` body `{ContextType, ContextItemId, UseDefaultValue, Value}` | **400 if an assignment already exists** for that context. |
| Update | `PUT …/customfields/{id}/updateAssigned` same body | **400 if no assignment exists.** |
| Unassign | `POST …/customfields/{id}/unassign` | Out of scope; never called. |

**Route inconsistency (confirmed):** the "HTTP Request" headings give `/api/v3/customfields/{id}/assign` and `/updateAssigned`; every code sample uses `/api/v3/automation/customfields/{id}/assign` and `/updateAssigned`. The portal allowlists exactly these two documented forms and uses **only the one validated on the tenant** (section 5). No other route is ever called.

Undocumented and therefore not assumed: maximum value length (the portal caps at 255, matching stored values), Boolean and Date value formats (the portal sends `true`/`false` and `YYYY-MM-DD`; read-back verification catches a mismatch, and live validation must confirm them), eventual-consistency timing (bounded read-back retries).

## 3. Flow

1. **Fields** — a super admin refreshes definitions from VSA X and marks which device-capable, not read-only, not expired fields the portal may edit (optionally "needs approval").
2. **Devices** — select in the inventory (selection kept across pages; "all matching" resolves to a fixed list) or paste/upload a list. The matching engine classifies every input (section 4).
3. **Preview** (background job) — reads, per device, the device-level assignment (`usage`) and the effective value (`devices/{id}/customfields`). Action per device: *Assign* (no device-level assignment), *Update* (device-level value differs; overwrite warning), *Skip — already correct*, *Requires review* (current value could not be read), *Blocked* (not a workstation, gone from inventory, field not editable).
4. **Confirm** — explicit, within 30 minutes of the preview. Jobs over the engineer limit need the bulk capability; jobs over the integration's approval threshold, or for a field marked "needs approval", wait for a different administrator.
5. **Execute** (Celery, one device at a time, rate-limited) — per device: re-check customer/workstation/field; re-read the assignment (concurrent change → skipped for review); commit *sending*; one POST or PUT, never repeated; read back with bounded retries. Results: *Verified*, *Already correct*, *Failed*, *Verification failed*, *Verification pending*, *Unknown outcome*, *Skipped*, *Cancelled*.
6. **History and report** — every job with per-device results; CSV, or XLSX with Summary / Successful / Skipped / Failed / Not found / Ambiguous sheets; failed devices can seed a new job (full preview again).

### 3a. Placeholder mode (CFA-10, 2026-11-25)

A job created with `only_if_empty: true` (one value for all devices, for example `TBD`) changes only devices without a value:

| Device-level assignment | Effective value | Action |
|---|---|---|
| none | none | Assign |
| none | inherited, empty | Assign |
| none | inherited, non-empty | Skip — has a value from the organisation, site or group |
| empty | — | Update (fills the empty value; no overwrite acknowledgement) |
| non-empty (≠ requested) | — | Skip — already has a value |
| = requested | — | Skip — already set |

Before each write the device-level assignment is read again; a value that appeared after the preview ends as *Skipped* (`has_value_now` or `changed_since_preview`). Devices with a write attempt get `Asset.details_refresh_requested_at`, so the next sync re-reads their details.

The inventory filter `custom_field` / `custom_field_state` (`missing`, `set`, `equals`, `not_equals`, `missing_or_equals`, `not_read`) / `custom_field_value` works on the values stored by the latest sync (`DeviceCustomField`, approved names only, case-insensitive). *Missing* requires the device's custom fields to have been read (fetch `collected` or `carried_forward`).

## 4. Matching precedence

1. VSA device ID (exact, current snapshot of the selected customer).
2. Serial number (only when the column is mapped as serial; must be unique).
3. FQDN (`hostname.domain`, exact, case-insensitive).
4. Hostname (exact, case-insensitive; narrowed by expected organisation/site/group when supplied).

No fuzzy matching. Classes: *matched, not found, multiple matches* (user must pick), *duplicate input, invalid identifier, outside the selected customer* (only for customers the user may see; otherwise *not found*, so nothing leaks), *unsupported device* (servers by SRV-01 rules, non-workstation types). Asset tag is not collected from VSA X and is reported as unsupported.

## 5. Enabling writes (operator)

All in the portal, super admin only (Settings → Integrations → Edit):

1. **Token**: the integration's API token is used (one token is enough). Optional separate write token entered in
   the portal (`POST /integrations/{id}/write-credential/`), Fernet-encrypted and bound to the integration and the
   purpose "write", or `write_credential_ref = env:VSA_WRITE_<NAME>`; when set, it is used instead.
2. **Validate on a test workstation** (`POST /integrations/{id}/validate-custom-field-route/`, explicit
   `confirm_test_device`; same logic as `manage.py vsa_custom_field_validate`): tries the heading form, falls back to
   the sample form only on 404, reads the value back and records the route that worked (audited).
3. Enable "Assign custom fields", set the approval threshold; Custom Fields → Field overview: mark editable fields.

`VSA_CUSTOM_FIELD_WRITES_ENABLED` (default true) is only a server emergency stop: false blocks every write.

Fixture integrations need none of these (writes go to an in-process fake).

## 6. Permissions (existing roles)

| Capability | Viewer | Engineer | Customer admin | Super admin |
|---|---|---|---|---|
| View fields, jobs, history (`customer.read`) | ✓ | ✓ | ✓ | ✓ |
| Prepare / import / preview / cancel (`customer.custom_field.assign`) | | ✓ | ✓ | ✓ |
| Apply (confirm) and retry jobs (`customer.custom_field.approve`) | | | ✓ | ✓ |
| Approve jobs needing a second approval (`customer.custom_field.approve`, not own) | | | ✓ | ✓ |
| Export report (`customer.export`) | as granted | ✓ | ✓ | ✓ |
| Field settings, integration switches, write token, route validation (`system.manage`) | | | | ✓ |

## 7. Deviations from the request

* **Concurrency is fixed at one write at a time per job.** VSA X allows 3,600 requests/hour per endpoint and every write is followed by reads; parallel writes would add risk without a meaningful speed-up. The pace follows the integration's request rate.
* **No live validation has been performed.** All tests use fixtures; the route, Boolean/Date formats and inheritance behaviour must be confirmed with step 5.2.
