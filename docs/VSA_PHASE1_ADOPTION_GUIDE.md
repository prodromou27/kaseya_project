# Existing project adoption guide — VSA only

## Preserve progress

Use existing source code, database migrations, test suites and Git history as the actual implementation baseline. Never reinitialize the repository or restart task P0-01 solely because new VSA specifications were added.

The original `docs/TASKS.md` remains the historical task register. The new `docs/PHASE1_TASKS.md` is a VSA-only coverage checklist. Create `docs/VSA_PHASE1_CROSSWALK.md` listing, for each new task, the corresponding original task, existing source files, test proof, and the state `DONE_VERIFIED`, `PARTIAL`, `MISSING`, `BLOCKED_VENDOR` or `BLOCKED_APPROVAL`.

## Task mapping

| Old task IDs | New VSA task IDs | Reuse strategy |
|---|---|---|
| P0-01 through P0-09 | VSA0-01 through VSA0-05 | Keep monorepo, Compose, identity, RBAC, audit, UI foundation |
| P1-01 through P1-04 | VSA1-01 through VSA1-06 | Extend existing VSA connector, sync, mapping, device UI |
| P1-05 through P1-08 | VSA3-01 through VSA3-02 | Keep software catalog and comparison work |
| P1-09 | VSA2-04, VSA3-05 | Add scoped multi-sheet XLSX/PDF beside existing CSV |
| P2-01 through P2-02 | VSA3-03, VSA3-04, VSA3-07 | Windows update data differs from third-party patch deployment |
| P2-03 through P2-07 | VSA3-05/06, VSA4-04 | Extend reports, scheduling, history |
| P3-* and P4-* | Deferred | No new IT Glue or Autotask development now |
| P5-* | VSAP-* | Production hardening for VSA-only release |
| New | VSA2-01/02/03/05 | Excel onboarding, reconciliation and group network reporting |
| New | VSA4-01 through VSA4-06 | Agent, disk, security, notifications and changes |
| Approval-gated new | VSA5-* | Move approval and verification, never live-enabled by default |

## Scope and security precedence

- `docs/PHASE1_SCOPE.md` defines the **current release scope**; don't delete broader roadmap documents.
- Existing root `AGENTS.md` and `CLAUDE.md` continue to govern coding. The most restrictive security rule wins in a conflict.
- Existing vendor integrations remain read-only. Device moves require a separate explicit authorization and pilot; implement dormant controls only until approved.
- Don't confuse installed-software version older than catalog with a truly pending third-party patch. Validate vendor API/report data separately.
- No customer cross-access through URLs, joins, jobs, Excel comparisons, or exports.
- Keep last valid complete VSA snapshot on failed synchronization.

## Acceptance evidence

Claude should first create `docs/VSA_CURRENT_STATE.md` and `docs/VSA_PHASE1_CROSSWALK.md` from actual code/tests before starting major changes. Record each verified task in `docs/IMPLEMENTATION_EVIDENCE.md`. Never claim real VSA connectivity if only sanitized fixtures were tested.
