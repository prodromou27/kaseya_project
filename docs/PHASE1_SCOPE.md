# Phase 1 scope, product boundary and launch criteria

**Status:** Required product specification; nothing in this document indicates that code is already built.

## In scope — VSA only

- Multi-customer portal identity, membership, RBAC, customer-to-VSA organization mapping, admin and audit.
- One or more VSA X on-prem/SaaS API instances with independent token ID/secret pairs, rate-limit accounting, capabilities and sync schedules.
- Organization/site/group tree; asset/device inventory, identity, agent status/version, last seen, OS, hardware/disks, network adapters, software, Windows updates, applied policies, security observations, notifications, approved custom fields.
- Per-device investigation, advanced search/saved views, per-group network aggregations, outliers and duplicates.
- Reviewed software reference catalog and **software version outdated** classification; pending third-party patch only where separate VSA API/report capability is verified live.
- Patch status including **available and installed OS updates**, assigned policy configuration; explicitly unknown/unscanned/unavailable states; no unsupported remediation claims.
- Excel/CSV onboarding reconciliation with reviewable mapping, deterministic matching, wrong group/site, ambiguous, missing, unexpected and historical runs.
- Snapshot comparisons, agent-health, disk capacity, reported security state, notifications, software/OS lifecycle references where externally reviewed data is approved.
- Customer-scoped CSV/XLSX/PDF and scheduled reports; source provenance and export history.
- **Optional, feature-gated VSA single-device move**: propose → independent approval → execute once → verify. It remains **disabled** until security and live pilot sign-off.

## Deliberately out of Phase 1

- IT Glue, Autotask PSA, Tenable and any other vendor integration (including connector configurations, credentials, sync logic, tables, screens or dependencies). Only extensibility contracts are acceptable.
- MCP server, chat, cloud AI processing or analytics telemetry.
- Remote script/task/workflow execution, patch deployment/approvals, reboots, policy edits, custom field edits, device deletions, creating VSA sites/groups, bulk move by default.
- Replacement of VSA core RMM/ITAM/PMS, remote-control or reporting engine.
- Unsupported access to internal VSA databases or scraping VSA web UI/Advanced Reporting pages.

## Internal release structure (all within VSA Phase 1)

| Gate | Name | Required result |
|---|---|---|
| VSA0 | Foundation | isolated customers, auth, RBAC, audit, PostgreSQL, Compose, tests |
| VSA1 | Inventory | connector, complete snapshots, devices, organizations/sites/groups, device search |
| VSA2 | Onboarding + networks | Excel import/reconciliation, group network and device identity, exports |
| VSA3 | Patch + software | version catalog, OS updates, policies, capability honesty, reports |
| VSA4 | Deep operations | agent/disk/security/notifications, lifecycle and history, schedules |
| VSA5 | Controlled move | optional, disabled until independent written authorization and live gate |
| VSAP | Production hardening | SSO/MFA, storage encryption, backups/restore, load tests, scoped pilot |

**Priority order:** complete VSA0–VSA3 before spending time on advanced operational embellishments. VSA5 never blocks a read-only production pilot.

## Quality/definition of done

A capability is done only with migrated schema, source adapter, customer-scoped service/API, working UI, fixtures, pass/fail tests, truthful unsupported states, audit and docs. Live-tenant capability needs recorded authorized test evidence. `VERSION_OUTDATED`, `OS_UPDATE_AVAILABLE`, `THIRD_PARTY_PATCH_PENDING`, and `VULNERABILITY_CONFIRMED` are distinct claims.
