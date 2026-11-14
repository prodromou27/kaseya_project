# Application audit — 2026-11-14

Reviewed baseline: `595d3e3`, clean worktree. This is an existing Django/React application, not a documentation package. Preserve its normalized storage, migrations, vendor adapter and workflow services. Scope is VSA Phase 1 only. No production access or real credentials used.

## Initial evidence and limitations

- Read AGENTS.md, CLAUDE.md, README, architecture, database, security, integration, reporting and Phase 1 specifications; inspected routes, shared components, inventory/report queries and recent Git history.
- Baseline frontend: **68 tests passed** using `npm.cmd run test -- --run`. The first sandboxed attempt failed during esbuild configuration resolution (access denied); rerunning with the filesystem restriction lifted passed.
- Baseline backend: `python -m pytest -xq` failed during database setup because PostgreSQL was unavailable. No application test result can be inferred from that failure. The longer initial run was interrupted after repeated setup errors.
- No Docker executable or running local application stack was found initially. Deployment files and prior operator evidence exist; the deployed host has not been accessed in this audit.
- Prior `IMPLEMENTATION_EVIDENCE.md` reports a 342-device live synchronization. This is historical operator evidence, not field-level live validation by this run.
- Browser baseline and subsequent validation results are recorded below as they become available. Initial findings below are source observations, not claims of successful browser workflows.

## Workflow review

| Area | Existing behavior | Problems | Recommended changes | Severity | Status |
|---|---|---|---|---|---|
| Shell/navigation | Responsive header, customer selector, six main links, specialists hidden under More | Reconciliation, groups and investigation workflows hard to discover; no persistent scope context beside content | Workflow sections, active page context, searchable navigation, mobile close behavior | P1 | Remediated and fixture-verified |
| Dashboard | Health summary, last trend point, lifecycle, historical chart | Tiles open unfiltered destinations; health errors disappear; latest trend point can represent just one integration; missing source-health panel | Current customer aggregates, exact drilldowns, explicit failure/freshness and coverage | P1 | Remediated and fixture-verified |
| Devices | Customer-scoped server filtering, pagination, saved views | Only group_id read from URL; filters lost on back navigation; no column chooser; export omits several active filters; network/source-ID search differs in export | URL-owned filters/page, shared backend filter implementation, column chooser, complete export filters | P1 | Remediated and fixture-verified |
| Device detail | Overview, network, hardware/security, software, updates, policies, notifications, reconciliation, history | Long undifferentiated definition lists; fixed label columns and overflowing tabs at narrow widths; software device name is not a link | Investigation header, grouped fields, wrapping/scrolling tabs, direct device links | P1 | Remediated and fixture-verified |
| Software | Reviewed catalog/version classifications and installation drilldown | Local-only filter state; default outdated view obscures general installed inventory; device column lacks investigation link | Persistent classifications/search, device links, retain unavailable patch distinction | P1 | Remediated and fixture-verified |
| Windows updates | Available/installed rows, section states, severity totals, export | Pagination not reset on KB/state changes; misleading export while viewing status population; local-only filters | Reset pages, preserve filters, explicit export scope | P1 | Remediated and fixture-verified |
| Excel comparison | XLSX/CSV upload, sheets/headers, mapping/preview, async run, history, review, workbook | Upload/map/run is one long form; steps and prerequisites need clearer progression | Compact progress indicator and clearly separated phases; preserve deterministic matching | P1 | Remediated and fixture-verified |
| Groups/network | Hierarchy, group network view, expected subnet review; no registered network export at baseline | Specialist navigation hides primary workflow; source-ID ambiguity across instances needs validation | Visible operations section; review instance-key semantics before expansion | P1 | Source identity fixed; R10 export implemented and verified; live validation pending |
| Device health | Partitioned dimensions, threshold approvals, group summary, device list | Dashboard does not pass exact attention filter; filters local; threshold editor precedes investigation list | URL filters, direct attention selection, put investigation first | P1 | Remediated and fixture-verified |
| Inventory changes | Complete-generation comparisons and report | Availability depends on retained complete snapshots; cannot establish live volumes here | Preserve publication guard; browser and multi-instance checks | P2 | Requires live validation |
| Notifications | Redacted, budgeted per-device source observations | Must retain not-collected/failed distinction; recurring patterns need live validation | Keep source limits visible | P2 | Requires live validation |
| Lifecycle | Reviewed official-reference entries; unknown for unverified records | Demo dates are illustrative; production baselines require review | Preserve explicit provenance and unknown classification | P2 | Requires live validation |
| Reports | Registry, private CSV/XLSX/PDF, saved definitions/schedules/history | Device export filters/search diverge from list; status view may export another population | Share filter service and test API/export row parity | P1 | Remediated and fixture-verified |
| Administration | Settings, connectors, encrypted portal credentials, roles/catalog/audit | Approval default recently simplified; independent review gate needs operator decision | Document deployment gates and review actual settings; no privileged execution | P1 | Needs validation |
| Synchronization | Stage/publish, checkpoints, quarantine, per-kind budgets, resumable partial state | Recent timeout changes need current regression run; 100k-load task still open | Run existing regression suite, then bounded load evidence | P1 | Current regression suite passed; live/concurrent workload pending |
| Group movement | Vendor client remains read-only; no move execution | Approval workflow was missing at baseline | Implement internal proposal/review separately; vendor execution stays gated | P2 | Internal proposal/review implemented and verified; execution remains gated |

## Prioritized execution

First unchecked historical task: **P0-02**, current release equivalent **VSA0-02**. Compose boot is externally blocked by missing Docker. Do not mark it complete. Next implementable remediation: **CX-01** (filter/report parity), followed by **CX-02** (navigation, dashboard and investigation UX), with tests and browser evidence. See CODEX_REMEDIATION_BACKLOG.md.

## Security review boundary

This application audit includes source review of customer scoping, report authorization, input validation and vendor egress. It is not a completed independent security audit. The security-audit skill requires an external retained output directory and OS-enforced network/environment/resource isolation for attack reproduction; those controls have not been established here. Full six-phase security audit remains incomplete, with reason `isolated_security_execution_environment_unavailable`. No prior compatible security coverage ledger was supplied. Existing tests and scans are QA evidence, not a substitute for independent verification or production configuration review.

## Completed remediation evidence

See CODEX_VERIFICATION.md for current checks, failed intermediate checks and final outcomes. CX-00 through CX-09 cover the implemented review, filter/report parity, navigation, dashboard drilldowns, software/patch persistence, reconciliation progression, device investigation, source-qualified hierarchy, bounded performance and internal approval slices. The original application was preserved.

The baseline phone review found document overflow on device detail (812px), settings (675px), changes (481px) and policies (476px) in a 390px viewport. Shared tab/form corrections and contained tables resolve those cases. Current screenshots use synthetic fixtures, and production/vendor validation remains separate.

The entire redesign wish list is not claimed complete: dashboard organization/site/group controls, saved column layouts, dark theme and a fully separated reconciliation wizard remain refinements. Detailed health-list/report scalability and concurrent related-data load still need measurement. Production readiness and live API validation remain gated.
