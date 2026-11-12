# Changelog

All implementation claims require linked evidence. Use semantic versions for application releases once a working application exists.

## [Docs 0.1.0] — 2026-11-12

### Added
- Full project README and scope restrictions.
- Architecture and multi-customer database model.
- Verified public-documentation-based vendor API capability register and limitations.
- Security, AlmaLinux/Docker deployment, admin and engineer workflows.
- Reporting metric definitions, QA test matrix and production readiness gates.
- Implementation roadmap, task checklist, Codex/Claude agent instructions and decision log.

### Not implemented
- No source code for the Django/React application in this package.
- No deployed portal, working vendor connector, live customer data, tests, or production sign-off.

## [0.1.0-dev] — 2026-11-12 (unreleased; P0 foundation, commit `d799241`)

Evidence: [PHASE_ACCEPTANCE_P0.md](PHASE_ACCEPTANCE_P0.md).

### Added
- Django 5.2 LTS / DRF API on PostgreSQL 16 with customers, memberships, seeded roles and capabilities, integration instances and reviewed source mappings.
- Central customer-scope policy. Cross-customer access returns an audited 404.
- Local bootstrap admin, OIDC relying party (tested against a mock IdP), secure server-side sessions, CSRF protection and login throttling.
- Append-only audit trail (including a DB trigger), redacted JSON logging, request IDs and a standard error envelope.
- Customer-scoped async report jobs with private artifacts, CSV formula-injection defence and re-authorised downloads. The first report type is the audit-log CSV.
- React 19 / TypeScript SPA: login, customer selector, dashboard, customer administration, system administration, reports.
- Dockerfiles, Compose dev/prod files, nginx proxy, CI and security workflows.

### Security
- Upgraded djangorestframework 3.16.1 → 3.18.3 after pip-audit reported CVE-2026-114136/7/8.

### Not yet verified
- Docker Compose boot, CI execution, Entra ID SSO, and every vendor connector (none implemented yet).

## [App release] — Not yet released

Coding agent must add actual commits, passing test evidence, migrations, deployment/validation results and limitations before publishing an application version.
