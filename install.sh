#!/usr/bin/env bash
# Odyssey Kaseya Portal: one-command installer / updater for AlmaLinux 9/10 (also Rocky/RHEL), SELinux enforcing.
#
#   sudo ./install.sh                                   # interactive: asks for anything missing
#   sudo ./install.sh --hostname portal.example.com --admin-email you@example.com --vsa-host vsa.example.com --yes
#
# Re-running is safe: it keeps existing secrets, settings, certificate and data, applies any new options, rebuilds
# the images from the current checkout and restarts the stack (database migrations run automatically).
# To update: `git pull` then `sudo ./install.sh --yes`.
#
# What it does:
#   1. Installs OS packages, Docker CE + Compose plugin (replaces the podman-docker shim), Docker daemon policy.
#   2. Opens ports 80/443 in firewalld (to every source for now; see docs/DEPLOYMENT.md section 5 to restrict).
#   3. Writes .env.prod (hostname, VSA X host allowlist, local sign-in until Entra ID is configured).
#   4. Creates secrets: DB password, Django key, API-token encryption key, and a self-signed TLS certificate unless
#      you pass --cert/--key. Ownership, modes and SELinux labels are set by infra/almalinux/prepare-secrets.sh.
#   5. Builds and starts the stack, waits until it is healthy.
#   6. Creates the first super administrator (once) with a random password saved to /root/okp-initial-admin.txt.
#   7. Optionally (--backup-key) installs the encrypted nightly database backup.
#   8. Runs the read-only preflight checks and prints the result.
#
# The VSA X API token is NOT handled here: after signing in, a super admin adds it in Admin → Integrations →
# "Set API token" (stored encrypted). The VSA X server hostname must be allowed with --vsa-host.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: sudo ./install.sh [options]
  --hostname NAME          Portal DNS name used in the browser (default: this host's FQDN)
  --admin-email EMAIL      E-mail (login) of the first super administrator
  --vsa-host HOST[,HOST]   VSA X server hostname(s) the connector may call, e.g. vsa.example.com
  --cert FILE --key FILE   CA-issued certificate (full chain, PEM) and private key; default: self-signed
  --regen-cert             Replace an existing self-signed certificate (e.g. after changing --hostname)
  --backup-key FILE        GPG PUBLIC key (.asc) for encrypted nightly backups (enables the backup timer)
  --backup-target TARGET   Off-host rsync target for backups, e.g. backup@host:/srv/okp/ (needs SSH key setup)
  --skip-packages          Do not install/upgrade OS packages or Docker (already prepared host)
  --yes, -y                Non-interactive: never prompt (use defaults / given options)
  --help                   This text
EOF
}

HOSTNAME_ARG="" ADMIN_EMAIL="" VSA_HOSTS="" VSA_SET=0 CERT="" KEY="" REGEN_CERT=0 BACKUP_KEY="" BACKUP_TARGET=""
SKIP_PACKAGES=0 ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --hostname) HOSTNAME_ARG="${2:?}"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="${2:?}"; shift 2 ;;
    --vsa-host) VSA_HOSTS="${2-}"; VSA_SET=1; shift 2 ;;
    --cert) CERT="${2:?}"; shift 2 ;;
    --key) KEY="${2:?}"; shift 2 ;;
    --regen-cert) REGEN_CERT=1; shift ;;
    --backup-key) BACKUP_KEY="${2:?}"; shift 2 ;;
    --backup-target) BACKUP_TARGET="${2:?}"; shift 2 ;;
    --skip-packages) SKIP_PACKAGES=1; shift ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 64 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33mWARNING:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
interactive() { [ "$ASSUME_YES" -eq 0 ] && [ -t 0 ]; }
ask() {  # ask VAR "Prompt" default
  local __var=$1 prompt=$2 def=${3-} reply
  if interactive; then
    read -r -p "    $prompt${def:+ [$def]}: " reply
    printf -v "$__var" '%s' "${reply:-$def}"
  else
    printf -v "$__var" '%s' "$def"
  fi
}

[ "$(id -u)" -eq 0 ] || die "Run as root: sudo ./install.sh"
APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$APP_DIR"
[ -f compose.prod.yml ] && [ -f .env.prod.example ] || die "Run from the portal repository (compose.prod.yml not found)."
ENV_FILE="$APP_DIR/.env.prod"
SECRETS="$APP_DIR/secrets"
COMPOSE=(docker compose -f compose.prod.yml --env-file "$ENV_FILE")

# ---------------------------------------------------------------- 0. OS
step "Checking the operating system"
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  almalinux|rocky|rhel) info "${PRETTY_NAME}" ;;
  *) die "Unsupported OS (${PRETTY_NAME:-unknown}). This installer targets AlmaLinux 9/10." ;;
esac
case "${VERSION_ID%%.*}" in 9|10) ;; *) warn "Version ${VERSION_ID} is not 9 or 10; continuing." ;; esac
if command -v getenforce >/dev/null; then
  case "$(getenforce)" in
    Enforcing) info "SELinux enforcing" ;;
    Permissive) warn "SELinux is Permissive. Set SELINUX=enforcing in /etc/selinux/config (do not disable it)." ;;
    *) warn "SELinux is Disabled. Enable it (enforcing) and reboot; the stack is labelled for SELinux." ;;
  esac
fi

# ---------------------------------------------------------------- 1. packages + Docker
if [ "$SKIP_PACKAGES" -eq 0 ]; then
  step "Installing OS packages"
  dnf -y -q install dnf-plugins-core policycoreutils-python-utils container-selinux chrony firewalld openssl git curl \
    tar gnupg2 rsync util-linux
  systemctl enable --now chronyd >/dev/null

  step "Installing Docker CE and the Compose plugin"
  if rpm -q podman-docker >/dev/null 2>&1; then
    dnf -y -q remove podman-docker
    info "removed the podman-docker shim"
  fi
  if ! rpm -q docker-ce >/dev/null 2>&1; then
    repo=https://download.docker.com/linux/rhel/docker-ce.repo
    dnf config-manager --add-repo "$repo" >/dev/null 2>&1 || dnf config-manager addrepo --from-repofile="$repo"
    dnf -y -q install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  info "$(docker --version)"
fi
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  die "Docker CE with the compose plugin is required."
fi

step "Applying the Docker daemon policy"
install -d -m 0755 /etc/docker
if ! cmp -s infra/almalinux/daemon.json /etc/docker/daemon.json; then
  [ -f /etc/docker/daemon.json ] && cp -p /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%Y%m%d%H%M%S)"
  install -m 0644 infra/almalinux/daemon.json /etc/docker/daemon.json
  systemctl enable docker >/dev/null 2>&1
  systemctl restart docker
  info "installed /etc/docker/daemon.json (SELinux labels, log rotation, live-restore, no-new-privileges)"
else
  systemctl enable --now docker >/dev/null 2>&1
  info "unchanged"
fi
docker info --format '{{json .SecurityOptions}}' | grep -q selinux || warn "Docker reports no SELinux support."

# ---------------------------------------------------------------- 2. firewall
step "Opening ports 80 and 443"
if systemctl is-enabled firewalld >/dev/null 2>&1 || [ "$SKIP_PACKAGES" -eq 0 ]; then
  systemctl enable --now firewalld >/dev/null 2>&1 || true
fi
if systemctl is-active firewalld >/dev/null 2>&1; then
  firewall-cmd -q --permanent --add-service=http --add-service=https
  firewall-cmd -q --reload
  info "firewalld: http, https allowed from any source"
else
  warn "firewalld is not running; nothing to open."
fi
info "Note: Docker-published ports bypass firewalld zones. To restrict sources later, see docs/DEPLOYMENT.md §5."

# ---------------------------------------------------------------- 3. .env.prod
step "Writing settings (.env.prod)"
get_env() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 || true; }
set_env() {  # set_env KEY VALUE (VALUE already validated: no newlines, no quotes)
  if grep -q "^$1=" "$ENV_FILE"; then
    sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$1" "$2" >>"$ENV_FILE"
  fi
}
if [ ! -f "$ENV_FILE" ]; then
  install -m 0600 .env.prod.example "$ENV_FILE"
  FIRST_INSTALL=1
else
  chmod 0600 "$ENV_FILE"
  FIRST_INSTALL=0
fi

current_host=$(get_env PORTAL_HOSTNAME)
[ "$current_host" = "portal.example.internal" ] && current_host=""
if [ -z "$HOSTNAME_ARG" ]; then
  default_host=$(hostname -f 2>/dev/null || hostname)
  # A bare "localhost"-style name is useless to browsers: default to this server's first IPv4 address instead.
  if [[ "$default_host" != *.* || "$default_host" == localhost* ]]; then
    default_host=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | head -1 || true)
  fi
  ask HOSTNAME_ARG "Portal hostname or IP (what users will open)" "${current_host:-$default_host}"
fi
[[ "$HOSTNAME_ARG" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$ ]] \
  || die "Invalid hostname: $HOSTNAME_ARG"
HOSTNAME_ARG=${HOSTNAME_ARG,,}

if [ "$VSA_SET" -eq 0 ]; then
  ask VSA_HOSTS "VSA X server hostname(s), comma-separated (empty = none yet)" "$(get_env CONNECTOR_ALLOWED_HOSTS_VSA_X)"
fi
VSA_HOSTS=${VSA_HOSTS// /}
VSA_HOSTS=${VSA_HOSTS,,}
VSA_HOSTS=${VSA_HOSTS#https://}
[[ "$VSA_HOSTS" =~ ^[a-z0-9.,-]*$ ]] || die "Invalid --vsa-host (hostnames only, no https:// or paths): $VSA_HOSTS"

set_env OKP_VERSION "$(git rev-parse --short HEAD 2>/dev/null || echo local)"
set_env PORTAL_HOSTNAME "$HOSTNAME_ARG"
set_env PORTAL_BIND_ADDRESS "0.0.0.0"
set_env CONNECTOR_ALLOWED_HOSTS_VSA_X "$VSA_HOSTS"
# Let the portal be opened by this server's IPv4 address(es) too (no DNS needed).
SERVER_IPS=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | paste -sd, - || true)
set_env PORTAL_EXTRA_HOSTS "$SERVER_IPS"
if [ "$FIRST_INSTALL" -eq 1 ]; then
  # No Entra ID app registration yet: local sign-in. Switch to OIDC later (docs/DEPLOYMENT.md §6).
  set_env LOCAL_LOGIN_ENABLED true
  set_env OIDC_ENABLED false
fi
info "hostname: $HOSTNAME_ARG"
info "also reachable by IP: ${SERVER_IPS:-(none detected)}"
info "VSA X hosts allowed: ${VSA_HOSTS:-(none yet: re-run with --vsa-host to add)}"
info "sign-in: $( [ "$(get_env OIDC_ENABLED)" = "true" ] && echo "Entra ID (OIDC)" || echo "local accounts" )"

# ---------------------------------------------------------------- 4. secrets + TLS
step "Preparing secrets and the TLS certificate"
install -d -m 0750 "$SECRETS"
if [ -n "$CERT" ] || [ -n "$KEY" ]; then
  [ -s "$CERT" ] && [ -s "$KEY" ] || die "--cert and --key must both point to non-empty files."
  openssl x509 -in "$CERT" -noout 2>/dev/null || die "$CERT is not a PEM certificate."
  cert_pub=$(openssl x509 -in "$CERT" -noout -pubkey | openssl sha256)
  key_pub=$(openssl pkey -in "$KEY" -pubout 2>/dev/null | openssl sha256)
  [ "$cert_pub" = "$key_pub" ] || die "The certificate and key do not match."
  install -m 0640 "$CERT" "$SECRETS/tls_cert.pem"
  install -m 0640 "$KEY" "$SECRETS/tls_key.pem"
  info "installed the provided certificate"
elif [ ! -s "$SECRETS/tls_cert.pem" ] || [ "$REGEN_CERT" -eq 1 ]; then
  san="DNS:$HOSTNAME_ARG"
  for ip in $(hostname -I 2>/dev/null); do
    [[ "$ip" == *:* ]] && continue
    san="$san,IP:$ip"
  done
  ( umask 077
    openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 825 -subj "/CN=$HOSTNAME_ARG" \
      -addext "subjectAltName=$san" -keyout "$SECRETS/tls_key.pem" -out "$SECRETS/tls_cert.pem" 2>/dev/null )
  warn "Generated a SELF-SIGNED certificate ($san). Browsers will warn; replace it with a CA-issued one:"
  info "sudo ./install.sh --cert /path/fullchain.pem --key /path/privkey.pem --yes"
else
  info "kept the existing certificate"
fi
infra/almalinux/prepare-secrets.sh "$SECRETS" | sed 's/^/    /'

# ---------------------------------------------------------------- 5. build + start
step "Building images (first run takes several minutes)"
"${COMPOSE[@]}" build --pull
step "Starting the stack"
if ! "${COMPOSE[@]}" up -d --remove-orphans; then
  "${COMPOSE[@]}" ps -a
  "${COMPOSE[@]}" logs --tail 30 || true
  die "A container failed to start (see the status and logs above; SELinux: ausearch -m avc -ts recent)."
fi
info "waiting for the portal to become ready..."
ready=0
for _ in $(seq 1 60); do
  if curl -fsSk --max-time 5 --resolve "$HOSTNAME_ARG:443:127.0.0.1" \
       "https://$HOSTNAME_ARG/api/v1/health/ready/" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 5
done
if [ "$ready" -ne 1 ]; then
  "${COMPOSE[@]}" ps
  "${COMPOSE[@]}" logs --tail 40 backend proxy || true
  die "The portal did not become ready within 5 minutes (see the logs above; SELinux: ausearch -m avc -ts recent)."
fi
info "ready: https://$HOSTNAME_ARG/"

# ---------------------------------------------------------------- 6. first administrator
step "First super administrator"
CRED_FILE=/root/okp-initial-admin.txt
if [ "$(get_env LOCAL_LOGIN_ENABLED)" != "true" ]; then
  info "local sign-in is disabled; skipping (administrators sign in with Entra ID)."
else
  if [ -z "$ADMIN_EMAIL" ]; then
    # The login only needs to look like an e-mail address; it does not have to be a real mailbox.
    default_email="admin@$HOSTNAME_ARG"
    [[ "$HOSTNAME_ARG" == *[a-z]*.*[a-z]* ]] || default_email="admin@portal.local"
    ask ADMIN_EMAIL "Administrator e-mail (login)" "$default_email"
  fi
  [[ "$ADMIN_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || die "Invalid e-mail: $ADMIN_EMAIL"
  pwdir=$(mktemp -d)
  trap 'rm -rf "$pwdir"' EXIT
  ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=\n' | cut -c1-24)"
  # The password reaches the container as a read-only file (never in argv, env, logs or the image).
  printf '%s' "$ADMIN_PASSWORD" >"$pwdir/pw"
  chown root:10001 "$pwdir/pw"; chmod 0640 "$pwdir/pw"
  set +e
  out=$("${COMPOSE[@]}" run --rm --no-deps -T -e RUN_MIGRATIONS=0 \
        -e BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/okp-bootstrap-pw -v "$pwdir/pw:/run/okp-bootstrap-pw:ro,z" \
        backend python manage.py bootstrap_admin --email "$ADMIN_EMAIL" 2>&1)
  rc=$?
  set -e
  rm -rf "$pwdir"
  if [ $rc -eq 0 ]; then
    ( umask 077
      printf 'Portal:   https://%s/\nLogin:    %s\nPassword: %s\nCreated:  %s\n' \
        "$HOSTNAME_ARG" "$ADMIN_EMAIL" "$ADMIN_PASSWORD" "$(date -u +%FT%TZ)" >"$CRED_FILE" )
    info "created $ADMIN_EMAIL; the password is in $CRED_FILE (root only)."
    info "Store it in your password manager, then delete that file."
  elif grep -q "already exists" <<<"$out"; then
    info "a super administrator already exists; nothing to do."
  else
    printf '%s\n' "$out" | tail -5 >&2
    die "Could not create the administrator."
  fi
  unset ADMIN_PASSWORD
fi

# ---------------------------------------------------------------- 7. backups (optional)
if [ -n "$BACKUP_KEY" ]; then
  step "Encrypted nightly database backups"
  [ -s "$BACKUP_KEY" ] || die "--backup-key file not found: $BACKUP_KEY"
  grep -q "PRIVATE KEY BLOCK" "$BACKUP_KEY" && die "That is a PRIVATE key. Give the PUBLIC key; the private key stays offline."
  install -d -m 0700 /etc/okp /etc/okp/gnupg /var/backups/okp
  GNUPGHOME=/etc/okp/gnupg gpg --batch --quiet --import "$BACKUP_KEY"
  fpr=$(GNUPGHOME=/etc/okp/gnupg gpg --batch --with-colons --show-keys "$BACKUP_KEY" | awk -F: '/^fpr/{print $10; exit}')
  [ -n "$fpr" ] || die "Could not read the key fingerprint."
  # Trust exactly this imported key for encryption (no web of trust on this host).
  echo "$fpr:6:" | GNUPGHOME=/etc/okp/gnupg gpg --batch --quiet --import-ownertrust
  if [ ! -f /etc/okp/backup.env ]; then
    install -m 0600 infra/backup/backup.env.example /etc/okp/backup.env
  fi
  sed -i -e "s|^APP_DIR=.*|APP_DIR=$APP_DIR|" -e "s|^GPG_RECIPIENT=.*|GPG_RECIPIENT=$fpr|" /etc/okp/backup.env
  if [ -n "$BACKUP_TARGET" ]; then
    sed -i -e "s|^OFFHOST_TARGET=.*|OFFHOST_TARGET=$BACKUP_TARGET|" -e "s|^REQUIRE_OFFHOST=.*|REQUIRE_OFFHOST=1|" /etc/okp/backup.env
  elif grep -q "^OFFHOST_TARGET=backup@backup-host.example.internal" /etc/okp/backup.env; then
    sed -i -e "s|^OFFHOST_TARGET=.*|OFFHOST_TARGET=|" -e "s|^REQUIRE_OFFHOST=.*|REQUIRE_OFFHOST=0|" /etc/okp/backup.env
    warn "No --backup-target: backups stay on this host only. Add an off-host target before production."
  fi
  sed "s|/opt/okp|$APP_DIR|g" infra/backup/okp-backup.service >/etc/systemd/system/okp-backup.service
  install -m 0644 infra/backup/okp-backup.timer /etc/systemd/system/okp-backup.timer
  systemctl daemon-reload
  systemctl enable --now okp-backup.timer >/dev/null
  if systemctl start okp-backup.service; then
    info "first backup OK (files in /var/backups/okp)"
  else
    warn "The first backup run failed: journalctl -u okp-backup.service -n 30"
  fi
fi

# ---------------------------------------------------------------- 8. preflight
step "Preflight checks"
set +e
infra/almalinux/preflight.sh | sed 's/^/    /'
pf=${PIPESTATUS[0]}
set -e

cat <<EOF

$(printf '\033[1m')Done.$(printf '\033[0m') Portal: https://$HOSTNAME_ARG/   (preflight failures: $pf)
Also by IP: $(printf '%s' "$SERVER_IPS" | sed -e 's#[^,][^,]*#https://&/#g' -e 's#,#  #g')

Next steps:
  1. Sign in as the administrator (password in $CRED_FILE on first install).
  2. Admin → Integrations → add a VSA X integration (base URL https://<your VSA host>), then "Set API token"
     with a READ-ONLY token, then "Test connection". The host must be allowed: sudo ./install.sh --vsa-host <host> -y
  3. Map VSA organisations to customers (Admin → Mappings), approve, then enable the integration.
  Update later with: git pull && sudo ./install.sh -y
EOF
