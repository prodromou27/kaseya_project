#!/usr/bin/env bash
# Read-only AlmaLinux host preflight for compose.prod.yml. Changes nothing. Run from the repo root:
#   sudo infra/almalinux/preflight.sh
# Exit code = number of FAIL checks. WARN items need an operator decision. NOT yet validated on the target host.
set -uo pipefail

fails=0
pass() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }

# OS
if [ -r /etc/os-release ] && . /etc/os-release && [ "${ID:-}" = "almalinux" ]; then
  case "${VERSION_ID%%.*}" in 9|10) pass "AlmaLinux ${VERSION_ID}" ;; *) warn "AlmaLinux ${VERSION_ID} (plan targets 9/10)" ;; esac
else
  warn "not AlmaLinux (${PRETTY_NAME:-unknown})"
fi

# SELinux
if command -v getenforce >/dev/null; then
  [ "$(getenforce)" = "Enforcing" ] && pass "SELinux enforcing" || fail "SELinux is $(getenforce); keep it Enforcing"
  rpm -q container-selinux >/dev/null 2>&1 && pass "container-selinux installed" || fail "container-selinux not installed"
else
  warn "getenforce not found"
fi

# Docker Engine (not the podman-docker shim)
if command -v docker >/dev/null; then
  if docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
    pass "Docker Engine $(docker version --format '{{.Server.Version}}')"
  else
    fail "docker CLI present but no Docker Engine reachable (is this the podman-docker shim?)"
  fi
  rpm -q podman-docker >/dev/null 2>&1 && fail "podman-docker shim installed; use Docker CE as documented" || true
  docker compose version >/dev/null 2>&1 && pass "$(docker compose version)" || fail "docker compose plugin missing"
  if docker info --format '{{json .SecurityOptions}}' 2>/dev/null | grep -q selinux; then
    pass "Docker daemon SELinux support on"
  else
    fail "Docker daemon SELinux support off (set \"selinux-enabled\": true, see infra/almalinux/daemon.json)"
  fi
  systemctl is-enabled docker >/dev/null 2>&1 && pass "docker.service enabled at boot" || fail "docker.service not enabled"
else
  fail "docker not installed"
fi

# Firewall and time
systemctl is-active firewalld >/dev/null 2>&1 && pass "firewalld active" || warn "firewalld not active"
if command -v chronyc >/dev/null && chronyc tracking 2>/dev/null | grep -q "Leap status *: Normal"; then
  pass "time synchronised (chrony)"
else
  fail "time not synchronised (chrony): TLS, OIDC and VSA timestamps depend on it"
fi

# Repository files
[ -f .env.prod ] && pass ".env.prod present" || fail ".env.prod missing (copy .env.prod.example)"
if [ -f .env.prod ]; then
  perm=$(stat -c %a .env.prod); [ "$perm" = "600" ] && pass ".env.prod mode 600" || warn ".env.prod mode $perm (use 600)"
fi
for f in django_secret_key postgres_password oidc_client_secret tls_cert.pem tls_key.pem; do
  p="secrets/$f"
  if [ ! -e "$p" ]; then fail "$p missing"; continue; fi
  owner=$(stat -c '%U:%g %a' "$p")
  case "$f" in tls_*) want="root:101 640" ;; *) want="root:10001 640" ;; esac
  [ "$owner" = "$want" ] && pass "$p $owner" || fail "$p is $owner, expected $want (run prepare-secrets.sh)"
  if command -v getenforce >/dev/null && [ "$(getenforce)" != "Disabled" ]; then
    case "$(stat -c %C "$p")" in
      *container_file_t*) pass "$p labelled container_file_t" ;;
      *) fail "$p SELinux label is not container_file_t" ;;
    esac
  fi
done
[ -s secrets/oidc_client_secret ] || warn "secrets/oidc_client_secret is empty (OIDC cannot work)"

# Free disk for images, database and report/onboarding volumes
avail=$(df -BG --output=avail /var/lib/docker 2>/dev/null | tail -1 | tr -dc 0-9)
[ -n "$avail" ] && { [ "$avail" -ge 20 ] && pass "/var/lib/docker ${avail}G free" || warn "/var/lib/docker only ${avail}G free"; }

echo "---- ${fails} failing check(s)"
exit "$fails"
