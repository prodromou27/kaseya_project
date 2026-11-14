# Product roadmap and delivery gates

**State:** Design baseline as of 2026-11-12. **P0 (`d799241`), P1 (`23550d1`) and P2 Windows updates, reports and history (`c483a8f`) are implemented and fixture-tested.** Their gates stay open until a Docker boot, a green CI run, a live pilot and owner sign-off (see the PHASE_ACCEPTANCE_P0/P1/P2 records). P3–P5 are planned. Use `TASKS.md` for implementation tracking.

## Objectives

- Eliminate repetitive cross-console lookup for Odyssey engineers.
- Produce defensible customer-scoped asset, software-version and OS update reports.
- Make reporting repeatable and historical without vendor API overload.
- Expand to IT Glue and Autotask PSA without compromising security or data correctness.

## Milestones

| Stage | Deliverables | Acceptance gate | Dependencies |
|---|---|---|---|
| P0 Foundation | Django/DRF, React, PostgreSQL, Compose, SSO skeleton, role/customer scope, audit | Logged-in user sees only assigned customer; all negative tests pass | Approved repo, design docs |
| P1 VSA + software | Token connector, asset/software sync, mapping, software catalog, comparator, inventory UI | Fixture tests + source-UI pilot counts and evidence | API read-only token, approved pilot |
| P2 OS updates + reports | Available/installed OS update models, dashboards, CSV/XLSX/PDF, schedule and historical generation | Metrics consistent with exports; stale/unknown handling correct | P1, report branding inputs |
| P3 IT Glue | Safe field allowlist, org/configuration sync, reviewable asset match | No passwords; mapping/reconciliation tests | Approved IT Glue key/region |
| P4 Autotask PSA | API-only user, zone discovery, companies/tickets, analytics | Ticket counts/source UI compare; no cost/secret data | Approved restricted API user |
| P5 Production readiness | Entra OIDC MFA, vault, backup+restore, monitoring, load test, security sign-off | Formal go/no-go checklist passes | All prior gates and internal approvals |

## Release targets (not dates)

**MVP release:** P0 + P1 + basic CSV of VSA software compliance. It is meaningful even if IT Glue and PSA are not yet connected.

**First internal pilot release:** P0–P2, including XLSX/PDF, history, and role/customer-scoped schedules.

**Complete initial application release:** P0–P5, three vendor connectors, approved security and operational validation.

Avoid time estimates until resources, actual vendor response/volume, and test environments are known.

## Prioritization rationale

VSA inventory and software-version reporting deliver the core requested outcome. IT Glue/PSA provide secondary context; add them after data correctness and authorization are proven. Explicit per-device third-party patch applicability remains **unsupported/unverified** until vendor documentation and pilot evidence prove it; do not block basic software-version analytics on that feature.

## Non-goals and deferred items

- MCP/AI assistant (separate decision).
- Managed Services Hub integration.
- Existing custom asset-management app integration.
- Autonomous patch deployment, remote access, VSA policy changes or PSA ticket writes.
- IT Glue password retrieval.
- Tenable vulnerability correlation (future phase; no claims of vulnerability state in initial release).
- Public customer self-service access.

## Risk register

| ID | Risk | Mitigation |
|---|---|---|
| R1 | Third-party patch API does not expose applicability | Label version comparison honestly, catalog provenance and unknowns |
| R2 | Customer mapping error causes leakage | Manual approval, uniqueness constraints, quarantine, IDOR tests |
| R3 | Vendor API throttling during bulk sync | Budget, checkpoint, concurrency cap, incremental where supported |
| R4 | Sensitive IT Glue/PSA content copied unnecessarily | Endpoint/field allowlist, redaction, minimization |
| R5 | Stale inventory used in reports | Source timestamps, stale banners, formal report generation gate |
| R6 | Report data loss or corrupted history | Atomic generations, off-host backup, restore drills |
| R7 | Restricted customer data handling | Contract review before onboarding, separate deployment if required |

## Progress reporting instructions

Coding agents must update `TASKS.md` checkboxes and this roadmap **only after verified implementation**, including commit, tests and gaps. Use `CHANGELOG.md` to record user-visible features with evidence. Never mark a stage complete on design artifacts alone.

## VSA application remediation - 2026-11-14

CX-00 through CX-09 are implemented and fixture-verified: workflow navigation/design system, responsive device investigation, exact current dashboard drilldowns, persistent filters, scoped selected-device exports, reconciliation progression, source-qualified groups and new R10 network CSV/XLSX/PDF, report history fixes, internal immutable move review, and measured health-summary/bundle improvements. Evidence: CODEX_VERIFICATION.md.

Production gates remain open. VSA0-02/P0-02 needs Docker; VSAP requires real SSO/MFA, approved key custody/backup/restore and a representative live pilot. Independent security review needs the required isolated execution environment. Move execution remains unavailable without a separately authorized implementation/pilot. Broader UI refinements and related-data/concurrent load remain in CODEX_REMEDIATION_BACKLOG.md. IT Glue/PSA/Tenable/MCP remain outside this improvement phase.

## CIDR-01 - onboarding group suggestions

Delivered legitimate temporary onboarding-group settings and reviewed source-qualified CIDR suggestions in device Operations. Transfers remain manual in VSA; no automatic placement correction. Fixture validation: 589 backend, 78 frontend, new browser workflow passed. Existing live/Docker/production gates remain open. See ONBOARDING_GROUPS.md.
