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

## 8. Backup and restore (VSAP-02)

**State:** The scripts are implemented and were exercised end to end on the development workstation against
PostgreSQL 16 (Git Bash, local `pg_dump`/`pg_restore`, a throwaway GnuPG key, `cp` standing in for rsync). They
have **not yet run on the AlmaLinux host**, against the Compose `db` container, or with a real off-host target.
**Do not onboard customers until the first host backup and an isolated restore drill have passed** and their
records are filed.

### 8.1 What is backed up

| Item | How | Notes |
|---|---|---|
| PostgreSQL (all portal data, audit log, history) | `infra/backup/backup.sh`: `pg_dump -Fc` inside the `db` container → `gpg --encrypt` to a public key | Plaintext never touches the backup host's disk |
| `secrets/`, `.env.prod` | Not by the script | Hold them in the approved vault/key custody (DEC-07) |
| `reports` volume | Not backed up | Report files expire after 24 h and can be regenerated from their pinned snapshot |
| `onboarding` volume | Not backed up | Uploads expire after 72 h. Comparison *results* are in PostgreSQL and are backed up |

### 8.2 One-time setup on the host

```bash
sudo dnf -y install rsync gnupg2 util-linux          # util-linux provides flock
sudo install -d -m 0700 /etc/okp /etc/okp/gnupg /var/backups/okp
# Import ONLY the backup PUBLIC key (the private key stays with the key custodians, offline):
sudo GNUPGHOME=/etc/okp/gnupg gpg --import okp-backup-public.asc
sudo GNUPGHOME=/etc/okp/gnupg gpg --list-keys --with-colons | awk -F: '/^fpr/{print $10; exit}'   # → GPG_RECIPIENT
sudo install -m 0600 infra/backup/backup.env.example /etc/okp/backup.env   # then edit (fingerprint, off-host target)
sudo install -m 0644 infra/backup/okp-backup.service infra/backup/okp-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now okp-backup.timer
sudo systemctl start okp-backup.service && journalctl -u okp-backup.service -n 20   # first run, check "off-host copy ok"
```

Each run writes `okp-db-<UTC>.dump.gpg` plus `.sha256` and `.json` (size, checksum, key fingerprint, app version)
to `/var/backups/okp`, and copies all three off-host. It keeps `RETENTION_DAYS` of local copies, and never deletes
the newest one. Exit codes: `0` ok; `1` failed (no partial file is left); `2` the local backup is ok but the
off-host copy is missing or failed. The systemd unit then shows as failed, so alert on it.

### 8.3 Restore drill (isolated host only)

Run it on a segregated host with its own PostgreSQL and the portal image, never on production. The custodian makes
the **private** key available there for the drill only.

```bash
RESTORE_DB=restore_$(date +%Y%m%d) DRILL_OPERATOR=<name> DRILL_APPROVER=<name> \
  infra/backup/restore-drill.sh /path/to/okp-db-<UTC>.dump.gpg /path/to/drill-records
```

The drill does the following:

1. Verifies the sha256 checksum.
2. Creates a **new** database, refusing any name that doesn't start with `restore_`.
3. Decrypts into a private temp directory and runs `pg_restore --exit-on-error --jobs N`.
4. Runs `manage.py restore_check` against the restored database. This checks for unapplied migrations, that all
   integrity and append-only triggers are present, that no rows cross customers, that every current generation is
   published, and that an active super admin exists. It also reports key counts.
5. Writes a JSON drill record: times, backup, checksum, restore duration, verification report, operator and
   approver.

The run exits 0 only if everything passes. Compare the record's counts with the production `restore_check` output
taken at backup time, and file the record with the actual RPO/RTO (DEC: the approved targets).

Locally verified behaviour (2026-11-13):

* A backup of 130 assets and 88 audit events was restored in 4 s, and the restored counts matched the source.
* A tampered file fails with a sha256 mismatch.
* `RESTORE_DB=portal` is refused.
* A missing off-host target exits 2.
* A failing dump exits 1 and leaves no partial file.
* Retention removes files older than the window, and the newest backup is kept.

## 9. Monitoring (to wire up)

Health endpoints, container health, queue lag, sync failures, 401/429 from VSA X (the admin connection test shows
the reported limits), stale datasets, report failures, volume growth, backup failures, login anomalies and export
volume. Logs are JSON on stdout with request IDs; ship them with the approved agent.

## 10. Incident notes

* A leaked vendor credential is an incident: revoke it in VSA X, rotate the reference, review connector logs and
  exports, and notify per contract.
* Never disable SELinux, TLS verification, the egress allowlist or customer isolation as a diagnostic shortcut.
* For an SELinux denial, check `ausearch -m avc -ts recent` and fix the label or rule. Do not use `setenforce 0`.
