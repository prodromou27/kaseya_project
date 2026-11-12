# Odyssey Kaseya Analytics & Reporting Portal

**Project state:** Specifications and implementation playbook only. **No runnable application is included in this documentation package.**

**Owner:** Odyssey internal engineering  
**Deployment target:** Internal AlmaLinux host, Docker Compose  
**Last design review:** 2026-11-12  
**Development model:** Independent repository; dedicated application; read-only vendor integration in v1.

## 1. Purpose

Build a production-oriented **multi-customer internal analytics and reporting portal** based on **Kaseya VSA X (VSA 10)**, with additional read-only adapters for **IT Glue** and **Autotask PSA**. Engineers will investigate device inventory, installed applications, outdated software versions, available Windows OS updates, documentation mismatches, and ticket trends. Users must be able to export trustworthy, customer-scoped reports and monitor synchronization health.

**Explicit exclusions:** This is **not** the Managed Services Hub, not the existing custom asset-management platform, not a replacement for Kaseya VSA, not a ticketing system, and not an MCP server. An AI/MCP adapter is optional future work only, subject to a separate security decision. No vendor write endpoints, remote execution, patch deployment, password/secret retrieval, or automated ticket modifications in v1.

## 2. Desired outcomes

- One customer selector with strictly enforced backend customer-scoped results.
- Workstation/server inventory with asset details, source identifiers, and last successful sync.
- Software-version intelligence with **Current, Outdated, Newer, Unknown, Unsupported, and Excluded** states.
- OS update availability and installed update views, using the VSA X fields actually documented and confirmed.
- Professional customer reports (CSV, XLSX, PDF) and scheduled runs.
- IT Glue configuration reconciliation and Autotask ticket analytics without modifying the vendors.
- Transparent completeness, staleness, source lineage and exception reporting.

## 3. Technology and architectural decisions

| Layer | Selection | Notes |
|---|---|---|
| Backend | Python 3.12+, Django 5.2 LTS, Django REST Framework | Modular monolith, typed services where feasible |
| Frontend | React 19, TypeScript, Vite, Tailwind, accessible component library | Server-side filtering and pagination |
| Database | PostgreSQL 16+ | Tenant-keyed reporting store and historical snapshots |
| Jobs | Celery + Redis | Collection, snapshots, report generation, schedules |
| Auth | Microsoft Entra ID OIDC + MFA | Local bootstrap only for initial provisioning/dev |
| Proxy | Nginx or Caddy, HTTPS | No publicly accessible DB/Redis |
| Deployment | Docker Compose on AlmaLinux | Non-root images, persistent storage, backup/restore |
| Tests | pytest, Vitest, Playwright, security/contract tests | CI acceptance gates |

Use a **modular monolith**, not microservices. The portal owns reporting copies, **never** the vendor master records. Reports must use a published, complete snapshot and explain missing data.

## 4. Scope and release order

| Stage | Scope | Gate |
|---|---|---|
| P0 | Repository, auth/RBAC, customer mappings, audit, PostgreSQL, Docker, basic UI | Security and customer-isolation tests pass |
| P1 | VSA assets/software, resilient sync, version catalog and comparison | Verified fixtures + pilot customer accuracy |
| P2 | VSA available/installed OS updates, reporting exports, snapshots, schedules | Report correctness and freshness verified |
| P3 | IT Glue organizations/configurations and reviewable matching | No automatic merges or secrets |
| P4 | Autotask PSA companies/tickets, cross-system views | Company isolation and source evidence |
| P5 | Operational hardening, SSO validation, monitoring, restore and load tests | Production go/no-go checklist passed |

See [ROADMAP.md](docs/ROADMAP.md), [TASKS.md](docs/TASKS.md), and [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## 5. Repository layout to build

```text
odyssey-kaseya-portal/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── docs/                       # Copy these design documents here
├── backend/
│   ├── config/
│   ├── apps/
│   │   ├── accounts/ customers/ integrations/ inventory/
│   │   ├── software/ patching/ itglue/ autotask/
│   │   ├── reporting/ audit/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/{app,features,components,lib}/
│   └── package.json
├── infra/{nginx,backup}/
├── compose.dev.yml
├── compose.prod.yml
├── .env.example
└── .github/workflows/
```

*Directories are targets for the coding agent to implement, not files delivered in this package.*

## 6. Starting implementation with Codex or Claude Code

1. Create a new private Git repository (`odyssey-kaseya-portal`) and copy this package into its root. The package already places `AGENTS.md`, `CLAUDE.md`, and `README.md` at the root, with supporting documents under `docs/`.
2. Read [AGENTS.md](AGENTS.md), [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md), and [TASKS.md](docs/TASKS.md).
3. Give the coding agent the kickoff message from [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md). Implement **P0 foundation first**, then pass each acceptance gate.
4. Start in fixture/demo mode. Supply read-only API tokens only when security approval and the connector tests are complete.
5. Do **not** deploy to production or onboard restricted customer data before approvals, MFA, off-host backups, restore tests, and a verified audit trail.

## 7. Critical correctness rules

- VSA X `InstalledSoftware` is **installed software version inventory**, not proof that a third-party patch is missing or deployable.
- VSA X `AvailableUpdates` is documented as **operating-system available updates**, not an authoritative third-party patch applicability feed.
- Reference catalog versions may vary by product, channel, architecture, edition, and lifecycle. Preserve **Unknown** when safe comparison is impossible.
- Tenable is **not part of initial integrations**. A future vulnerability module must distinguish vulnerability findings/closure from version comparisons.
- An imported customer mapping is not trusted until reviewed. Customer names and hostnames are not unique identity keys.

## 8. Authoritative reference documentation

- [Kaseya VSA X REST API](https://api.vsax.net/) — Basic auth (`token_id:token_secret`), `GET /api/v3/assets`, device assets, `InstalledSoftware`, `AvailableUpdates`, `InstalledUpdates`.
- [Kaseya VSA 10 Help](https://help.vsa10.kaseya.com/).
- [IT Glue API](https://api.itglue.com/developer) — JSON:API, `x-api-key`, regional endpoints, `/organizations`, `/configurations`.
- [Autotask REST API](https://www.autotask.net/help/DeveloperHelp/) — API-only user, zone discovery, integration-code headers, query endpoints.
- [Docker Engine for RHEL-compatible systems](https://docs.docker.com/engine/install/centos/) — validate current AlmaLinux-specific compatibility before deployment.

These references must be rechecked during implementation. All product API assumptions requiring live validation are marked in [API_INTEGRATIONS.md](docs/API_INTEGRATIONS.md).

## 9. Document index

- [ARCHITECTURE.md](docs/ARCHITECTURE.md): layers, trust boundaries, sync pipeline, operational behaviors.
- [DATABASE.md](docs/DATABASE.md): normalized schema, indexes, history, relationship model.
- [API_INTEGRATIONS.md](docs/API_INTEGRATIONS.md): supported vendor APIs, adapter contracts and unknowns.
- [SECURITY.md](docs/SECURITY.md): identity, tenant authorization, secrets, encryption, audit and threat model.
- [DEPLOYMENT.md](docs/DEPLOYMENT.md): environments, AlmaLinux deployment, TLS, backup and operational runbooks.
- [ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md): customer onboarding, connectors, RBAC and catalog operations.
- [USER_GUIDE.md](docs/USER_GUIDE.md): engineering workflows and interpretation guidance.
- [REPORTING.md](docs/REPORTING.md): report definitions, formulas, evidence and formats.
- [TESTING.md](docs/TESTING.md): acceptance criteria and negative/security test cases.
- [ROADMAP.md](docs/ROADMAP.md): milestone and work breakdown.
- [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md): exact coding-agent execution process.
- [TASKS.md](docs/TASKS.md): atomic issue-ready implementation tasks.
- [DECISIONS.md](docs/DECISIONS.md): design choices and open approval questions.
- [CHANGELOG.md](docs/CHANGELOG.md): documentation release history.
