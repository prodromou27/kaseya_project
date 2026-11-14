# VSA Phase 1 functional gap analysis

Baseline `595d3e3`, 2026-11-14. Status is based on inspected code and existing tests; this run's execution evidence is tracked separately.

| Capability | Code status | Evidence / outstanding validation |
|---|---|---|
| Customer sessions/RBAC and source mappings | Implemented | Existing authorization and IDOR tests; current PostgreSQL rerun pending |
| Inventory ingestion and atomic snapshots | Implemented | Existing failure/replay/publication tests; current regression and large-load evidence pending |
| Device list and investigation | Implemented but defective UX | Filter persistence/export parity and responsive investigation need correction |
| Installed software/version compliance | Implemented | Catalog approval/comparator; software-version status is distinct from patch applicability |
| Windows available/installed updates | Implemented | Missing sections explicit; per-device budgets/carry-forward; scan timestamp not established |
| Third-party patch applicability/deployment | Unavailable / further vendor verification required | Public asset inventory and policy APIs do not establish authoritative deployment state |
| Failed update/reboot pending | Unavailable / further vendor verification required | Do not derive from available KBs or version mismatch |
| Onboarding XLSX/CSV compare/history/review/export | Implemented, workflow clarity needs improvement | Deterministic matching, ambiguous rows, snapshot pins; real spreadsheet pilot pending |
| Hierarchy/network observations | Implemented | Group identity across multiple instances and live fields need validation; endpoint inventory is not topology |
| Agent health/thresholds | Implemented | Snapshot observations; no live monitoring assertion |
| Inventory differences | Implemented | Complete snapshots only; no fabricated actor or precise change time |
| Reports/schedules/history | Implemented with filter gaps | Protected artifact service and CSV/XLSX/PDF; no external mail delivery enabled |
| Controlled group movement | Internal propose/review implemented and fixture-verified; execution gated | Immutable snapshot/destination, separate permissions, expiry, independent approval and audit; no execute route or vendor write credential |
| Lifecycle dates | Implemented catalog, production data pending | Only reviewed official sources classify; demo dates illustrative |
| Large inventories / 100k benchmark | Not verified | VSA4-06 remains open |
| Docker deployment/real SSO/MFA/approved pilot | External gates | Preserve gates; prior host evidence is not current independent validation |

Official API reference re-opened 2026-11-14: https://api.vsax.net/ (available). https://help.vsa10.kaseya.com/ returned HTTP 404 through the research tool. No new vendor endpoint is required for the first remediations; all operate on portal-owned data. No live API requests were performed.

## Remediation update

Device/report filters now share code, URL views survive navigation/reload, selected-device reports are scoped, and source-qualified hierarchy no longer merges instance IDs. The dashboard uses current customer aggregates. Software/patch drilldowns persist their filters. Internal group-change review is implemented with additive migrations; VSA execution remains disabled. Group-network CSV/XLSX/PDF (R10) was missing from the registry and is now implemented with pinned source identity and missing-data rows. See CODEX_VERIFICATION.md for tested status and remaining refinements.
