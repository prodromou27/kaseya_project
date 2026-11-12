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

## Issue escalation

A decision blocking production safety cannot be overridden by the coding agent. Record task blocked, responsible owner, impact, safe fixture-mode fallback and evidence required to unblock. For application structure or UI details, the agent may make reasonable changes and record an ADR.
