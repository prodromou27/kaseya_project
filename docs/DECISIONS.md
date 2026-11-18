# Architecture decision record and open questions

**Document state:** Initial decisions adopted for design; production approvals remain outstanding.

## Adopted decisions

| ID | Decision | Reason | Status |
|---|---|---|---|
| ADR-001 | Dedicated independent portal | Separate product from Managed Services Hub and existing ITAM app | Accepted design |
| ADR-002 | Django REST + React + PostgreSQL | Familiar engineering ecosystem, modular service boundaries, reliable reporting | Accepted design |
| ADR-003 | Asynchronous sync & complete generations | Avoid API overload and partial reporting corruption | Accepted design |
| ADR-004 | Customer ID attached to every scoped record | Prevent multi-customer leaks and simplify audit | Mandatory |
| ADR-005 | Read-only vendor integration in v1 | Minimize operational risk; no patch/ticket actions | Mandatory |
| ADR-006 | Reviewed software reference catalog | Source APIs expose installed versions, not guaranteed missing third-party patch applicability | Mandatory |
| ADR-007 | Microsoft Entra OIDC for production | Central identity/MFA/account lifecycle | **Not required (2026-11-15, product owner).** Local portal accounts are the production sign-in; the OIDC code stays available but disabled |
| ADR-008 | Docker Compose on AlmaLinux | Approved internal host pattern | Proposed pending operations validation |
| ADR-009 | No secret retrieval from IT Glue | Reporting requirement does not need privileged credential content | Mandatory |
| ADR-010 | Per-customer data-processing approval | Contractual restrictions vary by customer | Mandatory |
| ADR-011 | Role capabilities defined in code (`apps/accounts/roles.py`); `Role` table seeded by migration | Capabilities cannot drift through runtime edits and stay reviewable in code review | Implemented (P0) |
| ADR-012 | Customer-scoped denials return 404 (not 403) and are audited | Prevents customer-existence leaks while keeping denial evidence | Implemented (P0) |
| ADR-013 | `SECURE_HSTS_PRELOAD` off by default; `security.W021` silenced only while it is off | The portal is an internal host; the preload list is for public domains | Implemented (P0) |
| ADR-014 | Customers are archived, users disabled, integrations disabled — never hard-deleted | Preserves audit, report and mapping history; FKs use `PROTECT` | Implemented (P0) |
| ADR-015 | Fixture integration instances must use `https://*.invalid` and may not hold credential references | A fixture record can never resolve to a real endpoint or be mistaken for live data | Implemented (P0) |
| ADR-016 | OIDC users matched by (issuer, subject) only; auto-provisioned users get no grants; email collisions need admin linking | Prevents account takeover by email; least privilege | Implemented (P0, mock IdP) |
| ADR-018 | Collect VSA X per approved mapping with `$filter=OrganizationId eq <int>`; quarantine any other org | Unmapped organisations are never fetched; integer-only IDs rule out OData injection | Implemented (P1) |
| ADR-019 | Publish a generation only when `TotalCount` is stable across pages and unique records reconcile | `$skip` paging over a changing source can silently miss records | Implemented (P1) |
| ADR-020 | Architecture-specific catalog references are classified `unknown` for VSA X data | `InstalledSoftware` has no architecture field (docs-verified) | Implemented (P1) |
| ADR-021 | Catalog imports and aliases need a reviewer other than the submitter (`CATALOG_REQUIRE_SEPARATE_REVIEWER`) | Poisoned reference versions are a listed threat | Implemented (P1) |
| ADR-022 | Revoking a mapping immediately hides its published data from customer views and reports | A wrong mapping is a leak; revocation must be effective at once | Implemented (P1) |
| ADR-023 | Alias matching is exact or prefix only (no regex) | Avoids ReDoS and over-broad, hard-to-review matches | Implemented (P1) |
| ADR-024 | Per-device OS-update status vocabulary (collected / not_collected / not_supported / not_requested / failed / carried_forward) | A missing section must never read as "0 missing updates" | Implemented (P2) |
| ADR-025 | InstalledUpdates collected per device within a configurable budget, least recently collected first, carry-forward labelled with its original time | The only documented source is a per-device endpoint (3600 req/h per token+endpoint) | Implemented (P2) |
| ADR-026 | `InstalledAt` stored verbatim, never converted | The documented example has no timezone | Implemented (P2) |
| ADR-027 | Schedules deliver in-portal only; owner and recipients re-authorised per run; `(schedule, slot)` DB-unique | DEC-09 (no e-mail yet); duplicate and revocation safety | Implemented (P2) |
| ADR-028 | Regeneration re-pins to the original generation/evaluation IDs, constrained to the run's customer | Reproducible historical reports without cross-tenant pin forgery | Implemented (P2) |
| ADR-029 | One gated vendor write: approved group moves via `PUT /devices/{id}/move` (VSA5-EXEC) | Product owner chose to execute approved moves (2026-11-16). Off unless the server switch `VSA_GROUP_MOVE_EXECUTION_ENABLED`, the per-integration switch and a token are all set (amended 2026-11-18 by the product owner: the integration's API token is used unless an optional separate write token is set); requester cannot execute; approval must be recent and inventory unchanged; one attempt per proposal committed before sending, no retries; timeouts are "unknown" and resolved only by GET read-back; every step audited. The read-only client stays GET-only | Implemented (VSA5-EXEC); live validation pending |
| ADR-017 | Frontend pinned to proven majors (React Router 7, TanStack Table 8, Vite 7, TypeScript 5.9, ESLint 9) instead of the newest majors | Avoids building on APIs that are not yet verified; upgrade deliberately later | Implemented (P0) |

## Open decisions requiring authorized owners

| ID | Owner | Question | Default until decided |
|---|---|---|---|
| ADR-030 | Reference versions updated daily from the VSA 10 Application Catalog page; safe increases auto-approved (CAT-02) | Product owner (2026-11-17): the catalog must update automatically. The VSA X API has no catalog endpoint, so a daily job reads the fixed public page (https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm; constant URL, HTTPS with verified TLS, no redirects, 5 MB cap, public destination only, no credentials). A **higher** version for a product that already has a human-approved reference and no warning is published automatically by the inactive "VSA catalog (automatic)" account and audited (`catalog.vsa_auto_update`); new products, decreases, format warnings and new installed-name aliases wait for approval. This is a deliberate exception to two-person catalog review, limited to version increases of approved products. Switch off with `VSA_APP_CATALOG_AUTO_UPDATE=false` | Implemented (CAT-02); live fetch verified 2026-11-17 against the public page (303 entries parsed) |
| ADR-031 | Second gated vendor write: assign/update VSA X custom fields on workstations (CFA) | Product owner request (2026-11-18, custom field assignment specification). Exception to the v1 read-only rule (as ADR-029). Only the documented `POST …/customfields/{id}/assign` and `PUT …/customfields/{id}/updateAssigned` with `ContextType: Device`; unassign is never called. Off unless all of: server switch `VSA_CUSTOM_FIELD_WRITES_ENABLED`, per-integration switch, a route form confirmed on a test workstation (the documentation gives two forms) and a token (the integration's API token, or an optional separate write token; one token is enough, product owner 2026-11-18). Amended 2026-11-18: the whole setup (write token entered encrypted in the portal, test-workstation validation, switch) is done in the portal by a super admin; the server variable defaults to true and serves only as an emergency stop. Fields are editable only when a super admin allows them (device context, not read-only, not expired, never credential-like). Every job is previewed against live VSA values, explicitly confirmed (overwrites acknowledged), re-checked per device before sending, sent once (no retry of uncertain writes) and verified by read-back; engineers prepare and preview, only customer administrators or super admins apply (amended 2026-11-18) and, above the integration's threshold or for fields marked so, a second administrator | Implemented (CFA); live validation pending |
| DEC-01 | Odyssey security/privacy | Which customers may be imported into central reporting DB? | No restricted customer onboarding |
| DEC-02 | IT operations | Exact VM/host sizing, HA, PostgreSQL storage, backup/restore objectives? | Pilot only, no HA claim |
| DEC-03 | Identity administrator | Entra tenant, SSO app registration, access groups and MFA policy? | **Closed (2026-11-15, product owner): Entra ID is not required.** Production uses local portal accounts with the existing password policy, lockout/throttling, session timeout and audit |
| DEC-04 | Vendor admins | VSA token privilege scope, instances and pilot orgs? | Fixture mode |
| DEC-05 | Vendor admins | IT Glue region and safe configuration field allowlist? | Connector disabled |
| DEC-06 | Vendor admins | Autotask zone, copied restricted API user, permitted ticket fields? | Connector disabled |
| DEC-07 | Security/operations | Vault/KMS provider, rotation and outbound allowlist? | **Interim (2026-11-13, product owner):** the VSA X API token may be entered in the portal by a super admin, stored encrypted with a host-held key (see THREAT_MODEL R3). A vault remains the production target |
| DEC-08 | Reporting owner | Approved catalog sources, refresh/review cadence and exception owner? | Unknown classifications when not reviewed |
| DEC-09 | Business owner | Customer-specific retention schedules, report recipients and allowed email distribution? | Export delivery disabled until approved |
| DEC-10 | Team lead | First pilot customer and acceptance comparison baseline? | Synthetic demo only |
| DEC-11 | Security | Require four-eyes review (proposer ≠ approver) for source-mapping approval? | Single super-admin approval, audited |

## Issue escalation

A decision blocking production safety cannot be overridden by the coding agent. Record task blocked, responsible owner, impact, safe fixture-mode fallback and evidence required to unblock. For application structure or UI details, the agent may make reasonable changes and record an ADR.
