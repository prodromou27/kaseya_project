# Deployment and operations — AlmaLinux + Docker Compose

**State (2026-11-13):** This runbook describes the files in this repository as implemented. **None of it has been
executed on an AlmaLinux host yet.** No Docker host has been available, so `compose.prod.yml`, the Dockerfiles, the
nginx templates and the `infra/almalinux/*` scripts have only been syntax-checked (YAML/JSON parse, `bash -n`,
shellcheck). Record the first real run in `docs/IMPLEMENTATION_EVIDENCE.md`, and fix this document where reality
differs.

## 1. Target

| Environment | Purpose | Data |
|---|---|---|
| Developer workstation | Fixtures, tests (`compose.dev.yml` or local toolchain) | Fictional only |
| Integration/test AlmaLinux VM | First Compose boot, real sync mechanics, restore drill | Approved test scope |
| Production AlmaLinux VM | Odyssey internal access | Approved customers only |

The baseline is **AlmaLinux 9 or 10** with **SELinux enforcing** (never disabled), firewalld, chrony, and Docker CE
with the Compose plugin from Docker's repository. Confirm the support of the exact AlmaLinux minor release against
<https://docs.docker.com/engine/install/> at install time.

## 2. Services (`compose.prod.yml`)

| Service | Image | Runs as | Network | Notes |
|---|---|---|---|---|
| `proxy` | `okp-frontend` (nginx-unprivileged) | uid 101 | `web` | Publishes 80→8080 (redirect) and 443→8443 (TLS). Serves the SPA and proxies `/api` |
| `backend` | `okp-backend` (Gunicorn) | uid 10001 | `web`, `data` | Runs migrations at start (`RUN_MIGRATIONS=1`): keep a **single** backend replica |
| `worker` | `okp-backend` (Celery) | uid 10001 | `data`, `web` | Queues `maintenance,reports,sync_vsa`. Needs egress to the allowlisted VSA X host |
| `beat` | `okp-backend` (Celery Beat) | uid 10001 | `data`, `web` | Exactly one instance. Duplicate dispatches are also blocked by the DB |
| `db` | `postgres:16-alpine` | postgres | `data` (internal) | Named volume `pgdata` |
| `redis` | `redis:7-alpine` | redis | `data` (internal) | Named volume `redisdata` |

The app containers run with a read-only root filesystem, `cap_drop: ALL` and `no-new-privileges`. The `data`
network is `internal: true`, so PostgreSQL and Redis are never published. Private named volumes are `reports` and
`onboarding`; files in them are served only through Django after re-authorisation, never directly by nginx.

Health: `/api/v1/health/live/` (process) and `/api/v1/health/ready/` (database and dependencies). Readiness never
calls vendor APIs.

## 3. Host preparation (AlmaLinux)

Run as an administrator. Commands follow Docker's RHEL instructions; verify them against the current Docker
documentation before running.

```bash
# 3.1 OS and base packages
sudo dnf -y upgrade
sudo dnf -y install dnf-plugins-core policycoreutils-python-utils container-selinux chrony firewalld openssl git
sudo systemctl enable --now chronyd firewalld
getenforce                                   # must print: Enforcing

# 3.2 Docker CE, not the podman-docker shim that AlmaLinux can provide as "docker"
sudo dnf -y remove podman-docker || true
sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
#   AlmaLinux 10 / dnf5 syntax: sudo dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/rhel/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3.3 Daemon policy: SELinux labelling on, log rotation, live-restore, no-new-privileges
sudo install -m 0644 infra/almalinux/daemon.json /etc/docker/daemon.json
sudo systemctl enable --now docker
docker info --format '{{json .SecurityOptions}}'   # must include "name=selinux"
```

Docker socket access is equivalent to root. Do not add operators to the `docker` group casually. Use `sudo` with
audited accounts.

## 4. Application files and secrets

```bash
sudo mkdir -p /opt/okp && sudo chown "$USER": /opt/okp
git clone <approved-repo-url> /opt/okp && cd /opt/okp
git checkout <approved-release-tag>

cp .env.prod.example .env.prod && chmod 600 .env.prod   # then edit: PORTAL_HOSTNAME, OIDC_*, connector allowlist
sudo install -m 0640 -o root -g 101 /path/to/issued-cert.pem secrets/tls_cert.pem   # full chain
sudo install -m 0640 -o root -g 101 /path/to/issued-key.pem  secrets/tls_key.pem
sudo infra/almalinux/prepare-secrets.sh                 # generates DB password + Django key, fixes owners/modes/labels
sudo sh -c 'umask 077; cat > secrets/oidc_client_secret'   # paste the Entra client secret, then Ctrl-D
sudo infra/almalinux/prepare-secrets.sh                 # re-run: re-applies owner/mode/label to the new file
sudo infra/almalinux/preflight.sh                       # read-only checks; exit code = number of failures
```

**Why the ownership matters:** Compose (non-swarm) bind-mounts secret files with their *host* ownership and mode. The
containers are non-root, so each secret must be readable by the container's group and nobody else:

* `django_secret_key`, `postgres_password`, `oidc_client_secret`: `root:10001`, `0640`;
* `tls_cert.pem`, `tls_key.pem`: `root:101`, `0640`.

With SELinux enforcing they also need the type `container_file_t`. `prepare-secrets.sh` adds a persistent
`semanage fcontext` rule and runs `restorecon`. A root-only `0600` secret would stop the backend from starting.

Rules:

* Never put secrets in `.env.prod`.
* Never commit `secrets/` or `.env.prod`; both are git-ignored.
* Rotate a secret by replacing the file, re-running `prepare-secrets.sh`, and restarting the affected services.

Vendor API credentials are **not** created by these scripts. A VSA X token is used only after written approval
(DEC-04), through a credential reference configured in the portal.

## 5. Network and firewall

```bash
# Admin SSH only from the management range (example; adjust the zone/source to your standard)
sudo firewall-cmd --permanent --zone=public --remove-service=ssh
sudo firewall-cmd --permanent --zone=public --add-rich-rule='rule family="ipv4" source address="<mgmt-cidr>" service name="ssh" accept'
sudo firewall-cmd --reload
```

**Docker-published ports bypass firewalld zone rules.** Docker installs its own forwarding rules, so a zone rule
cannot restrict who reaches ports 80/443 published by `proxy`. To limit portal access to approved client ranges:

1. Set `PORTAL_BIND_ADDRESS` in `.env.prod` to the service interface IP, not `0.0.0.0`.
2. Add source restrictions in the `DOCKER-USER` chain, for example with firewalld direct rules. Replace
   `<client-cidr>` and `<if>`:

   ```bash
   sudo firewall-cmd --permanent --direct --add-rule ipv4 filter DOCKER-USER 0 -i <if> -s <client-cidr> -p tcp -m multiport --dports 8080,8443 -j RETURN
   sudo firewall-cmd --permanent --direct --add-rule ipv4 filter DOCKER-USER 1 -i <if> -p tcp -m multiport --dports 8080,8443 -j DROP
   sudo firewall-cmd --reload
   ```

   DOCKER-USER sees the **container** ports (8080/8443) after DNAT. The behaviour depends on the Docker and firewalld
   versions, so verify it from an allowed and a disallowed client.

**Outbound:** allow only DNS, NTP, the image registry (during deploy), the Entra endpoints, and the exact VSA X host
listed in `CONNECTOR_ALLOWED_HOSTS_VSA_X`. The application also enforces this host allowlist itself, plus a
private-address/SSRF check and mandatory TLS verification.

## 6. Build, start, bootstrap

```bash
cd /opt/okp
export COMPOSE="docker compose -f compose.prod.yml --env-file .env.prod"
$COMPOSE build --pull                    # or `pull` from the approved registry with OKP_VERSION set
$COMPOSE up -d
$COMPOSE ps                              # backend/worker healthy, proxy up
curl -fsS http://$PORTAL_HOSTNAME/healthz       # proxy liveness (HTTP listener only)
curl -fsS https://$PORTAL_HOSTNAME/api/v1/health/ready/   # end-to-end through TLS to Django

# One-time break-glass administrator (needs LOCAL_LOGIN_ENABLED=true temporarily; prompts for the password)
$COMPOSE run --rm -it -e LOCAL_LOGIN_ENABLED=true backend python manage.py bootstrap_admin --email admin@example.internal
```

Then sign in, configure Entra ID (OIDC), and set `LOCAL_LOGIN_ENABLED=false` once SSO works. **Never run
`seed_demo` on production**: it creates fictional demo tenants and users.

`restart: unless-stopped` together with `systemctl enable docker` brings the stack back after a reboot. Container
logs are rotated by `/etc/docker/daemon.json` (5 × 20 MB per container).

## 7. Release / upgrade

1. Take and verify a database backup (section 8) and note the current image tag for rollback.
2. `git checkout <new-tag>`; `$COMPOSE build --pull` (or pull the tagged images); then `$COMPOSE up -d`. The backend
   applies migrations on start.
3. Smoke test: health endpoints, sign-in, one customer's dashboard, a fixture or approved sync, and one report download.
4. Rolling back images is not enough if a migration is not backward compatible. Read the release's migration notes
   before upgrading.

## 8. Backup and restore — NOT IMPLEMENTED (VSAP-02)

No backup or restore tooling exists yet (`infra/backup/` is empty), so **do not onboard customers until VSAP-02 is
complete and a restore drill has passed**. The required scope:

* an encrypted, off-host PostgreSQL dump with checksum;
* the `reports`/`onboarding` volumes, or an accepted decision that they are regenerable or expiring;
* `secrets/` held in the approved vault;
* a documented RPO/RTO and an isolated restore drill.

## 9. Monitoring (to wire up)

Health endpoints, container health, queue lag, sync failures, 401/429 from VSA X (the admin connection test shows
the reported limits), stale datasets, report failures, volume growth, backup failures, login anomalies and export
volume. Logs are JSON on stdout with request IDs; ship them with the approved agent.

## 10. Incident notes

* A leaked vendor credential is an incident: revoke it in VSA X, rotate the reference, review connector logs and
  exports, and notify per contract.
* Never disable SELinux, TLS verification, the egress allowlist or customer isolation as a diagnostic shortcut.
* For an SELinux denial, check `ausearch -m avc -ts recent` and fix the label or rule. Do not use `setenforce 0`.
