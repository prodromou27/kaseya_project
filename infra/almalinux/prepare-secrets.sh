#!/usr/bin/env bash
# Prepare ./secrets for compose.prod.yml on an AlmaLinux (SELinux enforcing) host. Run as root from the repo root:
#   sudo infra/almalinux/prepare-secrets.sh
#
# - Generates django_secret_key, postgres_password and connector_encryption_key if missing (never prints them).
#   connector_encryption_key encrypts API tokens entered in the portal; back it up with the vault/key custodians:
#   without it, a restored database cannot decrypt those tokens (they must then be entered again).
# - Expects tls_cert.pem / tls_key.pem and oidc_client_secret to be placed by the operator (warns if missing;
#   creates an empty oidc_client_secret only when OIDC is not used).
# - Sets ownership/mode so the non-root containers can read *only* their own secrets:
#     app secrets  -> root:10001 0640  (backend/worker/beat user "portal", uid/gid 10001; postgres reads as root)
#     TLS secrets  -> root:101   0640  (nginx-unprivileged user, uid/gid 101)
# - Labels the directory container_file_t persistently (semanage fcontext + restorecon) so SELinux allows reads.
# Idempotent. NOT yet validated on the target host.
set -euo pipefail

SECRETS_DIR="${1:-$(pwd)/secrets}"
APP_GID=10001
NGINX_GID=101

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required." >&2; exit 1; }

umask 077
install -d -m 0750 -o root -g root "$SECRETS_DIR"

gen() {  # gen <file> <bytes>
  local f="$SECRETS_DIR/$1"
  if [ ! -s "$f" ]; then
    openssl rand -base64 "$2" | tr -d '\n' >"$f"
    echo "generated $1"
  else
    echo "kept existing $1"
  fi
}

gen django_secret_key 64
gen postgres_password 32
# Fernet key: URL-safe base64 of 32 random bytes.
if [ ! -s "$SECRETS_DIR/connector_encryption_key" ]; then
  openssl rand -base64 32 | tr -d '\n' | tr '+/' '-_' >"$SECRETS_DIR/connector_encryption_key"
  echo "generated connector_encryption_key"
else
  echo "kept existing connector_encryption_key"
fi

if [ ! -e "$SECRETS_DIR/oidc_client_secret" ]; then
  : >"$SECRETS_DIR/oidc_client_secret"
  echo "WARNING: created EMPTY oidc_client_secret. Put the Entra client secret there before enabling OIDC." >&2
fi
for f in tls_cert.pem tls_key.pem; do
  [ -s "$SECRETS_DIR/$f" ] || echo "WARNING: $SECRETS_DIR/$f is missing. Place the CA-issued certificate/key." >&2
done

for f in django_secret_key postgres_password oidc_client_secret connector_encryption_key; do
  chown root:"$APP_GID" "$SECRETS_DIR/$f"
  chmod 0640 "$SECRETS_DIR/$f"
done
for f in tls_cert.pem tls_key.pem; do
  if [ -e "$SECRETS_DIR/$f" ]; then
    chown root:"$NGINX_GID" "$SECRETS_DIR/$f"
    chmod 0640 "$SECRETS_DIR/$f"
  fi
done
# The directory must be traversable by both container users; files stay 0640.
chmod 0755 "$SECRETS_DIR"

if command -v getenforce >/dev/null && [ "$(getenforce)" != "Disabled" ]; then
  if command -v semanage >/dev/null; then
    semanage fcontext -a -t container_file_t "$SECRETS_DIR(/.*)?" 2>/dev/null \
      || semanage fcontext -m -t container_file_t "$SECRETS_DIR(/.*)?"
    restorecon -R "$SECRETS_DIR"
    echo "SELinux: labelled $SECRETS_DIR container_file_t (persistent)"
  else
    chcon -R -t container_file_t "$SECRETS_DIR"
    echo "SELinux: labelled with chcon (install policycoreutils-python-utils for a persistent rule)" >&2
  fi
fi
ls -lZ "$SECRETS_DIR" 2>/dev/null || ls -l "$SECRETS_DIR"
