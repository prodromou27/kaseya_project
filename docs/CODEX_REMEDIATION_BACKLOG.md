# Codex remediation backlog

Scope: preserve VSA Phase 1 implementation; no IT Glue, PSA, Tenable or MCP. Vendor writes stay disabled. Record only observed results; task completion does not close deployment gates.

| ID | Priority | Deliverable / acceptance | Dependencies | Status |
|---|---|---|---|---|
| CX-00 | P0 | Independent baseline, all-page source review, browser baseline, current tests | Local toolchain and fixture PostgreSQL | Completed and fixture-verified |
| CX-01 | P1 | Device list and CSV/XLSX/PDF share search/filter/sort semantics; URL filters/page survive navigation; tenant isolation regression; column chooser | Existing inventory query and pinned report service | Completed and fixture-verified |
| CX-02 | P1 | Workflow navigation, active customer scope, responsive investigation shell, consistent shared controls, visible errors/freshness | CX-00 | Completed and fixture-verified |
| CX-03 | P1 | Dashboard aggregates current data across approved sources and links to exact filtered populations | Existing health/software/patch summary APIs | Completed and fixture-verified |
| CX-04 | P1 | Software and patch filters survive navigation; device links; pagination resets; exports describe population | CX-01 | Completed and fixture-verified |
| CX-05 | P1 | Reconciliation progression, mapping preview and result review improved; fixture E2E and workbook evidence | Existing onboarding backend | Completed and fixture-verified |
| CX-06 | P1 | Device investigation header, responsive tabs and grouped overview; loading/error/removed asset states | CX-02 | Completed and fixture-verified |
| CX-07 | P1 | Multi-instance hierarchy/group identity checks; scope any detail/report ambiguity | PostgreSQL regression environment | Completed and fixture-verified |
| CX-08 | P2 | VSA4-06 bounded load/query evidence and necessary indexes | Current tests green; local PostgreSQL | Completed and fixture-verified |
| CX-09 | P2 | Internal proposal and independent group-move approval lifecycle, no vendor write execution | Source/destination identity and permissions | Completed and fixture-verified |
| CX-10 | Gate | Docker/AlmaLinux health, real SSO/MFA, secrets recovery, backup/restore, operator pilot | Approved environments and owners | Blocked externally |
| CX-11 | Gate | Independent security audit with ledger, source verification and isolated execution; dependency scans | Required isolation and separate retained audit directory | Scans passed; independent audit blocked by isolation environment |

Validation: Ruff + format, Django checks/migration drift, PostgreSQL pytest, frontend tests/types/lint/build, Playwright desktop/narrow workflows. No schema migration needed for filter/UX slices. Do not imply deployment or live vendor verification.

## Delivery boundaries

CX-08 completes the bounded normalized-inventory benchmark (100k devices), not concurrent production load or vendor ingestion throughput. CX-09 completes internal proposals/reviews, not VSA execution. No existing production gate is closed by these results. The first unchecked historical task remains P0-02 / VSA0-02 (Docker environment).

Remaining refinement work: dashboard sub-customer scope controls; saved column layouts; dark theme; a fully separated multi-screen reconciliation wizard; richer related-data/concurrent load; report branding review. Existing customer-first upload is retained so files always have an authorized owner before storage. These are not represented as completed by the narrower remediation acceptance conditions above.

Next acceptance work: approved representative pilot, Docker/AlmaLinux health, independent security environment and live field/capability verification. No real credentials may be used without approval. Detailed query timing and workload limitations: CODEX_PERFORMANCE.md. Production deployment/rollback: CODEX_DEPLOYMENT_AND_ROLLBACK.md.
