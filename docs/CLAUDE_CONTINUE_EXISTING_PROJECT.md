# CLAUDE CODE: Continue the EXISTING Odyssey Kaseya portal — VSA Phase 1

You are working in an **already-started project**. Do not start a new repository, replace existing documentation wholesale, rebuild finished modules, reset the database, overwrite migrations, or discard Git history and user changes.

## First: audit what actually exists

1. Read original `AGENTS.md`, `CLAUDE.md`, `README.md`, original `docs/TASKS.md`, plus `README_ADDENDUM.md`, `docs/VSA_PHASE1_ADOPTION_GUIDE.md`, `docs/PHASE1_SCOPE.md`, `docs/PHASE1_TASKS.md`, `docs/PHASE1_IMPLEMENTATION_PLAN.md`, `docs/VSA_OPERATIONS_REQUIREMENTS.md`, `docs/VSA_API_CAPABILITY_MATRIX.md`, `docs/ONBOARDING_RECONCILIATION.md`, `docs/GROUP_NETWORK_AND_MOVES.md`, `docs/SOFTWARE_AND_PATCH_INTELLIGENCE.md`, and `docs/PHASE1_TESTING.md`.
2. Inspect Git status and recent commits; list actual Django apps, migrations, DRF routes/services, React pages, Docker configuration, VSA connector, Celery tasks and tests. Record current functionality and execution evidence in `docs/VSA_CURRENT_STATE.md`. Do not assume old documentation checkboxes reflect the code.
3. Create `docs/VSA_PHASE1_CROSSWALK.md`. Map old P0/P1/P2 task IDs to new VSA0/VSA1/VSA2/VSA3/VSA4/VSA5/VSAP tasks, and assign each a status: `DONE_VERIFIED`, `PARTIAL`, `MISSING`, `BLOCKED_VENDOR`, or `BLOCKED_APPROVAL`. Name exact files/tests. **Never redo `DONE_VERIFIED` work.**
4. Run the project's available tests/lint/typecheck/build; record precise results and current failures. Do not claim anything was tested if it was not.

## Implementation scope

The **first release is Kaseya VSA X only**. Defer new IT Glue, Autotask PSA, Tenable and MCP work; preserve their existing designs and any already completed code, but do not prioritize them now. The project remains an independent multi-customer Django/React/PostgreSQL/Celery/Docker application.

Prioritize **missing work**, not new scaffolding: robust VSA device/asset and group hierarchy, device details and network, installed software and catalog comparison, Windows OS updates and patch policy views, CSV/XLSX onboarding reconciliation (found/wrong group/wrong site/missing/ambiguous/duplicate), group-level network insights, agent health, snapshots/history, and customer-scoped report generation.

Before implementing actual pending/failed/reboot third-party patch states, verify official VSA X API or officially supported reporting/export capability **on your installed VSA version**. An outdated installed software version is NOT proof of a pending applicable patch. Distinguish known, unknown, unsupported and stale states.

All vendor operations remain read-only. You may design and fixture-test a **disabled-by-default** device-group move approval workflow, but do not enable VSA write requests unless explicit authorization and independent approval have been obtained, with separate credentials, cross-customer validation, audit and post-change read-back.

## Execute

Select the highest-priority `PARTIAL` or `MISSING` VSA task from the crosswalk. Implement one vertical slice end-to-end: database migration, backend API/service, customer authorization, working frontend, errors, fixtures, tests, and docs. Validate the existing tests remain green. Repeat in dependency order without starting from scratch. Update checklists only with real evidence; retain original task history. Commit tested changes when permitted.

If credentials or vendor access are not available, finish fixture-based adapters and tests, label live checks `LIVE_VALIDATION_PENDING`, and continue nonblocked tasks.

**Start now by producing the current-state audit and task crosswalk for this repository, then implement the first missing VSA feature.**
