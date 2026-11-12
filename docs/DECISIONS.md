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
| ADR-007 | Microsoft Entra OIDC for production | Central identity/MFA/account lifecycle | Proposed pending IdP config |
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
| ADR-017 | Frontend pinned to proven majors (React Router 7, TanStack Table 8, Vite 7, TypeScript 5.9, ESLint 9) instead of the newest majors | Avoids building on APIs that are not yet verified; upgrade deliberately later | Implemented (P0) |

## Open decisions requiring authorized owners

| ID | Owner | Question | Default until decided |
|---|---|---|---|
| DEC-01 | Odyssey security/privacy | Which customers may be imported into central reporting DB? | No restricted customer onboarding |
| DEC-02 | IT operations | Exact VM/host sizing, HA, PostgreSQL storage, backup/restore objectives? | Pilot only, no HA claim |
| DEC-03 | Identity administrator | Entra tenant, SSO app registration, access groups and MFA policy? | No production access |
| DEC-04 | Vendor admins | VSA token privilege scope, instances and pilot orgs? | Fixture mode |
| DEC-05 | Vendor admins | IT Glue region and safe configuration field allowlist? | Connector disabled |
| DEC-06 | Vendor admins | Autotask zone, copied restricted API user, permitted ticket fields? | Connector disabled |
| DEC-07 | Security/operations | Vault/KMS provider, rotation and outbound allowlist? | No production credentials stored |
| DEC-08 | Reporting owner | Approved catalog sources, refresh/review cadence and exception owner? | Unknown classifications when not reviewed |
| DEC-09 | Business owner | Customer-specific retention schedules, report recipients and allowed email distribution? | Export delivery disabled until approved |
| DEC-10 | Team lead | First pilot customer and acceptance comparison baseline? | Synthetic demo only |
| DEC-11 | Security | Require four-eyes review (proposer ≠ approver) for source-mapping approval? | Single super-admin approval, audited |

## Issue escalation

A decision blocking production safety cannot be overridden by the coding agent. Record task blocked, responsible owner, impact, safe fixture-mode fallback and evidence required to unblock. For application structure or UI details, the agent may make reasonable changes and record an ADR.
