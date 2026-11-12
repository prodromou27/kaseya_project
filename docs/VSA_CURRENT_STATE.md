# VSA current state: audit of the existing implementation

**Audited:** 2026-11-13, at commit `8056734` on `main` (working tree clean apart from the 15 new Phase 1 documents).
**Method:** I inspected the code, migrations, routes and tests directly, and ran the checks listed below. Checkboxes in older documents were **not** taken as evidence.
**Missing input:** `README_ADDENDUM.md` is referenced by `docs/CLAUDE_CONTINUE_EXISTING_PROJECT.md` but does not exist in the repository.

## 1. Verification run at audit time

The environment was a Windows 11 workstation with Python 3.12.10, Node 24.22 and PostgreSQL 16.2 (a local disposable cluster). Docker is not installed.

| Check | Command | Result |
|---|---|---|
| Backend lint | `uv run ruff check .` | All checks passed |
| Migration drift | `manage.py makemigrations --check --dry-run` | No changes detected |
| Backend tests (PostgreSQL) | `uv run python -m pytest -q` | **324 passed** in 52 s |
| Frontend lint and types | `npm run lint && npm run typecheck` | clean |
| Frontend unit tests | `npx vitest --run` | **34 passed** |
| E2E (Playwright, fixture stack) | last full run at `c483a8f` (see PHASE_ACCEPTANCE_P2.md) | 16 passed. Not re-run for this audit because the code is unchanged since then |
| Docker Compose boot | — | **Never executed** (no Docker host) |
| CI workflows | — | **Never executed** (no remote) |
| Live VSA X calls | — | **None.** All connector evidence is docs and fixtures only |

## 2. What exists in code

**Django apps** (`backend/apps/`): `core`, `accounts`, `customers`, `integrations`, `audit`, `reporting`, `inventory`, `software`, `patching`. There are no IT Glue, Autotask, Tenable or MCP apps, which is consistent with Phase 1.

**Migrations:** 18 project migrations. They include PostgreSQL triggers for append-only audit, customer consistency (inventory, software and patching rows) and immutable catalog revisions.

**VSA connector** (`apps/integrations/vsa/`, `apps/integrations/http.py`):

| Capability | State |
|---|---|
| Basic token auth via `credential_ref` (`env:NAME`) | implemented, fixture-tested |
| `GET /api/v3/assets` (`$top=100`, `$skip`, `$filter=OrganizationId eq <int>`, `$orderby=Identifier`, include `Tags,AssetInfo,InstalledSoftware,Updates,AvailableUpdates`) | implemented, fixture-tested |
| `GET /api/v3/assets/:id?include=InstalledUpdates` (budgeted per device) | implemented, fixture-tested |
| `GET /api/v3/organizations` (admin discovery) | implemented, fixture-tested |
| `GET /api/v3/devices`, `/sites`, `/groups`, `/devices/:id/appliedpolicies`, `/patchmanagement/policies/:id`, `/ratelimits`, notifications, antivirus, custom fields | **not implemented** |
| Asset sections `IpAddresses`, `LocalIpAddresses`, `Disks`, `Security`, `PublicIpAddress` | **received but discarded** by the normaliser |
| Read-only GET-only client, path allowlist, DNS/SSRF egress checks, TLS always on, rate budget, Retry-After, no retry on 401/403 | implemented, tested |
| Any vendor write (including `PUT /devices/:id/move`) | not implemented. The client has no write method |

**Sync engine** (`apps/integrations/sync.py`): runs per approved mapping, with checkpointed pages, quarantine (org mismatch, malformed, customer conflict), `TotalCount` stability, a drop guard, atomic generation publish, tombstoning after complete crawls, in-worker re-authorisation, sync schedules (Celery Beat) and resumable partial runs.

**Data held per generation:** `AssetObservation` (hostname, description, type, group *name*, site ID, org ID, agent version, last seen, OS, manufacturer/model/serial, domain, tags, software status), `SoftwareInstallation`, `PatchObservation` and `DeviceOsUpdate` (available and installed OS updates with explicit statuses), and `ComplianceEvaluation`/`ComplianceResult`. **No group ID, site name, NIC, IP, disk or security observation is stored.**

**API routes:** 68 routes under `/api/v1/` (enumerated from the URL resolver at audit time). The customer-scoped ones are: assets (list, facets, detail), datasets, sync-runs, software (list, summary), software-exceptions, os-updates (list, summary, devices), reports, saved-views, report-definitions, report-schedules, trends, mappings, memberships and audit-events. The global ones are: reports (detail, download, regenerate, inbox), report-templates, catalog, integrations, sync-quarantine, sync-schedules, mappings review, users and roles.

**Reports (registry):** customer audit log, asset inventory (RPT-01), software compliance (RPT-03), OS updates (RPT-04), software distribution (RPT-05) and stale devices (RPT-06). All are available in CSV, XLSX and PDF with pinned snapshots and provenance. Each XLSX has **one data sheet** plus a provenance sheet; there are no multi-tab workbooks.

**Frontend pages:** Dashboard (with trend chart), Customers (detail, members, mappings, audit), Assets (list, saved views, detail with Overview, Installed software, OS updates and History tabs), Software versions, Windows updates, Reports (new, history, definitions and schedules, inbox), and Administration (mapping review, integrations, catalog, quarantine, sync schedules, users, audit). IT Glue and Autotask show "not implemented" placeholders.

**Not present anywhere:** an organisation/site/group explorer, group network view, NIC/IP/MAC search, Excel/CSV onboarding import and reconciliation, patch policy views, agent-health thresholds, disk/hardware/security views, notifications, custom fields, generation diff, lifecycle catalog, device-move workflow, and an explicit "third-party patch status unavailable" panel.

## 3. Vendor capability evidence

All of this comes from the public reference at https://api.vsax.net/, re-read on 2026-11-13. It is **not** live-tested. Details are in `backend/apps/integrations/vsa/capabilities.json` and `docs/VSA_LIVE_VALIDATION_LOG.md`.

* The 72 documented routes include `GET /devices`, `/devices/:id`, `/sites`, `/groups`, `/devices/:id/appliedpolicies`, `/patchmanagement/policies/:id`, `/patchmanagement/globalrules/`, `/ratelimits/`, `/auditlogs`, device notifications, antivirus and custom fields, and `PUT /devices/:deviceId/move`.
* **No documented route returns per-device third-party patch applicability or deployment, pending, failed or reboot state.** Patch policy `SoftwareRules` describe configuration only. Third-party deployment status is therefore `UNVERIFIED` and must be presented as unavailable.
* The docs show an error envelope `{"Data": null, "Meta": {"ResponseCode", "ErrorMessage"}}`. The adapter still acts on status codes only and never stores bodies.

## 4. Known gaps and risks carried forward

The P0/P1/P2 phase gates remain open (Docker boot, CI run, sign-off, live pilot). The per-phase limitations in `docs/PHASE_ACCEPTANCE_P0.md`, `PHASE_ACCEPTANCE_P1.md` and `PHASE_ACCEPTANCE_P2.md` still apply.
