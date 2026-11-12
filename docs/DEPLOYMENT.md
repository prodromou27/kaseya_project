# Deployment and operations — AlmaLinux + Docker Compose

**State:** Implementation instructions for the *future application*. This docs package does **not** include the backend/frontend/Compose source. Do not run these commands expecting the portal to start until the coding agent has created and tested the files.

## 1. Target environments

| Environment | Purpose | Data |
|---|---|---|
| Developer workstation | Rapid feedback, fixtures | Fictional only |
| Integration/test VM | PostgreSQL, real sync mechanics, controlled test credentials | Approved test scope |
| Production AlmaLinux VM | Odyssey internal access, HA/backup policy as approved | Approved customers only |

Suggested OS baseline: supported AlmaLinux 9/10 release compatible with selected Docker Engine/Compose versions; verify vendor packages and organizational support policy before installation. Keep SELinux enforcing.

## 2. Intended Docker services

- `proxy`: HTTPS, frontend assets, `/api` reverse proxy.
- `backend`: Django + Gunicorn, internal network.
- `worker-sync`: Celery collectors, separate queues and concurrency ceilings.
- `worker-reports`: Celery export generator.
- `beat`: singleton Celery Beat scheduler.
- `postgres`: persistent private DB, restricted account.
- `redis`: private broker, authentication/security config where supported.
- `backup`: scheduled encrypted off-host backups (or orchestrated on host with documented agent).

No publicly published ports for Postgres or Redis. Bind development ports to localhost or a restricted segment. In production, expose only approved proxy HTTPS port.

## 3. Prerequisites (to validate during implementation)

- Host sizing from pilot load (CPU/RAM/disk/IOPS); do not assume the 100k-asset design target is benchmarked.
- DNS name, CA-issued/internal TLS certificate, firewall allowlist and NTP.
- Secure image registry and repository access; `docker compose` plugin installed from a trusted repository.
- Microsoft Entra application registration / OIDC configuration.
- Approved vendor API service accounts and regional endpoints.
- Secrets vault or protected encrypted secret store with documented key custody.
- Encrypted off-host backup target and tested restore process.

## 4. Example project environment template (agent must produce `.env.example`)

```dotenv
APP_ENV=development
PUBLIC_BASE_URL=https://portal.example.internal
DJANGO_ALLOWED_HOSTS=portal.example.internal
DJANGO_SECRET_KEY=<inject-from-secret-store>
DATABASE_URL=postgresql://portal:<password>@postgres:5432/portal
CELERY_BROKER_URL=redis://redis:6379/0
OIDC_ISSUER_URL=https://login.microsoftonline.com/<tenant-id>/v2.0
OIDC_CLIENT_ID=<client-id>
OIDC_CLIENT_SECRET=<inject-from-secret-store>
REPORT_STORAGE_PATH=/var/lib/portal/reports
APP_LOG_LEVEL=INFO
```

Values are **examples only**, not working credentials. Production templates should avoid exposing passwords in a world-readable `.env`, prefer secret references/mounts and document rotation.

## 5. Implementation-time developer commands

The coding agent must make the following exact workflows operational and document any project-specific additions:

```bash
# After source and compose files are created:
cp .env.example .env
# Edit the environment safely; never commit .env

docker compose -f compose.dev.yml up -d --build
docker compose -f compose.dev.yml exec backend python manage.py migrate
docker compose -f compose.dev.yml exec backend python manage.py bootstrap_admin
# Only in a disposable DEMO environment:
docker compose -f compose.dev.yml exec backend python manage.py seed_demo

docker compose -f compose.dev.yml ps
```

Prefer automated migrations as an explicit deployment job rather than every app replica running them concurrently. Implement a proper `/health/live` and `/health/ready` (or documented equivalent); readiness checks must verify PostgreSQL and required internal services, not vendor API availability.

## 6. AlmaLinux host setup checklist

1. Install and patch supported AlmaLinux; create restricted administrator accounts.
2. Install supported Docker Engine/Compose and ensure Docker daemon is explicitly governed; **Docker socket access grants high privilege**.
3. Maintain SELinux in enforcing mode; for bind mounts set correct ownership/labels (e.g., approved `:Z`/`:z` volume semantics as needed) rather than disabling SELinux.
4. Harden firewall: admin SSH only from management ranges, HTTPS only from approved client ranges; deny DB/Redis externally.
5. Set up private DNS, TLS certificates, trusted corporate CA, NTP and outbound firewall destination rules.
6. Configure secure secret injection, logging, backup storage, monitoring and time synchronization.
7. Pull pinned images; scan, verify and deploy Compose prod profile.
8. Run smoke, auth, RBAC, sync, export and restore tests before onboarding customers.

## 7. Production deployment procedure (after implementation)

```bash
# Example command shape; use the approved tagged release
export PORTAL_VERSION=<approved-tag>
docker compose -f compose.prod.yml pull
docker compose -f compose.prod.yml run --rm backend python manage.py migrate --noinput
docker compose -f compose.prod.yml up -d
docker compose -f compose.prod.yml ps
```

Before migration: create restore-tested DB backup, identify rollback tag, plan downtime if schema changes are destructive. After deploy: health check, login, smoke test with fictional/approved account, verify schedules and alerts. Rollback of application images is not enough if schema migrations are irreversible; document backward-compatibility strategy.

## 8. Backup and restore

Create scripts and runbooks with:
- Database backup and integrity checks; encrypted artifact/credential-reference backups.
- Off-host retention and checksum verification.
- Recovery of application config, signing keys, OIDC settings, report storage and catalog revisions.
- Isolated restore drill using a fully segregated environment.
- Validation: user permissions, dataset generations, source timestamps, report regeneration, and audit continuity.

Restore exercises must record start/end, selected backup, checksum, exception list, actual RPO/RTO and approver.

## 9. Monitoring

Dashboard/alerts for API readiness, DB connections, queue lag, sync failures, source 401/429, vendor rate budgets, stale datasets, scheduled report failures, disk/report storage growth, backup failure, login anomalies and high export volume. Include correlation/request IDs. Create severity-based escalation guidance and incident runbooks.

## 10. Update and incident response

Use tagged releases, documented migrations and staging verification. Treat exposed vendor credential as an incident: revoke token in vendor, rotate vault secret, investigate connector logs and exports, notify affected customers per contractual requirements. Do not disable customer isolation as a diagnostic workaround.
