#!/usr/bin/env bash
# VSAP-02 encrypted PostgreSQL backup for the AlmaLinux production host.
#   sudo infra/backup/backup.sh [/etc/okp/backup.env]       (normally run by okp-backup.timer)
#
# 1. pg_dump (custom format) runs INSIDE the db container; the dump never touches disk unencrypted.
# 2. The stream is encrypted with GnuPG to a PUBLIC key (GPG_RECIPIENT fingerprint). The private key is NOT on this
#    host, so a compromised host cannot read its own backups.
# 3. sha256 + JSON manifest are written next to the backup, then copied off-host (OFFHOST_TARGET).
# 4. Local copies older than RETENTION_DAYS are removed (the newest backup is always kept).
# Exit codes: 0 ok; 1 backup failed; 2 backup ok locally but the off-host copy is missing/failed.
set -euo pipefail

CONFIG="${1:-/etc/okp/backup.env}"
# shellcheck source=/dev/null
[ -r "$CONFIG" ] && . "$CONFIG"

: "${BACKUP_DIR:?BACKUP_DIR is required}"
: "${GPG_RECIPIENT:?GPG_RECIPIENT (public key fingerprint) is required}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
APP_DIR="${APP_DIR:-/opt/okp}"
MIN_BYTES="${MIN_BYTES:-1024}"
REQUIRE_OFFHOST="${REQUIRE_OFFHOST:-1}"
OFFHOST_TARGET="${OFFHOST_TARGET:-}"
OFFHOST_CMD="${OFFHOST_CMD:-rsync -a --chmod=F0600}"
export GNUPGHOME="${GNUPGHOME:-/etc/okp/gnupg}"
# The container's own POSTGRES_USER/POSTGRES_DB are used, so no credentials are needed here.
PG_DUMP_CMD="${PG_DUMP_CMD:-docker compose -f $APP_DIR/compose.prod.yml --env-file $APP_DIR/.env.prod exec -T db sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Fc'}"

log() {
  local msg
  msg="$(date -u +%Y-%m-%dT%H:%M:%SZ) okp-backup: $*"
  echo "$msg"
  command -v logger >/dev/null && logger -t okp-backup -- "$*" || true
}

umask 077
mkdir -p "$BACKUP_DIR"
if command -v flock >/dev/null; then
  exec 9>"$BACKUP_DIR/.lock"
  flock -n 9 || { log "another backup is running; aborting"; exit 1; }
else
  log "WARNING: flock not available; concurrent runs are not prevented"
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="okp-db-$stamp.dump.gpg"
final="$BACKUP_DIR/$name"
tmp="$BACKUP_DIR/.$name.partial"
trap 'rm -f "$tmp"' EXIT

log "starting backup -> $name"
start=$(date +%s)
if ! bash -c "$PG_DUMP_CMD" | gpg --batch --yes --trust-model always --encrypt --recipient "$GPG_RECIPIENT" --output "$tmp"; then
  log "FAILED: dump or encryption failed"
  exit 1
fi
bytes=$(stat -c %s "$tmp")
if [ "$bytes" -lt "$MIN_BYTES" ]; then
  log "FAILED: encrypted dump is only $bytes bytes (< $MIN_BYTES)"
  exit 1
fi
mv "$tmp" "$final"
(cd "$BACKUP_DIR" && sha256sum "$name" >"$name.sha256")
sha=$(cut -d' ' -f1 "$final.sha256")
version="$(git -C "$APP_DIR" describe --tags --always 2>/dev/null || echo unknown)"
cat >"$final.json" <<JSON
{"file": "$name", "created_utc": "$stamp", "bytes": $bytes, "sha256": "$sha", "gpg_recipient": "$GPG_RECIPIENT",
 "format": "pg_dump -Fc | gpg --encrypt", "app_version": "$version", "duration_seconds": $(( $(date +%s) - start ))}
JSON
log "local backup ok: $bytes bytes sha256=$sha"

# Retention: delete old local copies, never the newest one.
newest="$(find "$BACKUP_DIR" -maxdepth 1 -name 'okp-db-*.dump.gpg' -printf '%f\n' | sort | tail -1)"
find "$BACKUP_DIR" -maxdepth 1 -name 'okp-db-*.dump.gpg*' -mtime +"$RETENTION_DAYS" ! -name "$newest*" -print -delete \
  | while read -r f; do log "retention removed $f"; done

if [ -z "$OFFHOST_TARGET" ]; then
  if [ "$REQUIRE_OFFHOST" = "1" ]; then
    log "FAILED: OFFHOST_TARGET is not set; an off-host copy is required"
    exit 2
  fi
  log "WARNING: no off-host copy configured (REQUIRE_OFFHOST=0)"
  exit 0
fi
# OFFHOST_CMD is parsed by bash so quoted options (e.g. rsync -e 'ssh -i key') survive; files are passed as "$@".
if bash -c "$OFFHOST_CMD \"\$@\"" okp-offhost "$final" "$final.sha256" "$final.json" "$OFFHOST_TARGET"; then
  log "off-host copy ok -> $OFFHOST_TARGET"
else
  log "FAILED: off-host copy to $OFFHOST_TARGET failed (local backup kept)"
  exit 2
fi
