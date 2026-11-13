#!/usr/bin/env bash
# VSAP-02 isolated restore drill. Run on a SEGREGATED host/database that holds the backup PRIVATE key, never on
# production:
#   RESTORE_DB=restore_20261113 DRILL_OPERATOR=alice DRILL_APPROVER=bob \
#     infra/backup/restore-drill.sh /path/okp-db-<stamp>.dump.gpg [record-dir]
#
# Steps: verify sha256 against the .sha256 file -> create a NEW empty database (name must start with "restore_") ->
# decrypt to a private temp file (0700 dir, removed on exit: pg_restore --jobs needs a seekable file, and decryption
# vs restore failures stay distinguishable) -> pg_restore --exit-on-error -> run VERIFY_CMD (manage.py restore_check
# against that database) -> write a JSON drill record (times, backup, checksum, duration, verification, operator).
# Exit code 0 only when every step and the verification pass.
set -euo pipefail

BACKUP="${1:?usage: restore-drill.sh <backup.dump.gpg> [record-dir]}"
RECORD_DIR="${2:-$(dirname "$BACKUP")/drills}"
: "${RESTORE_DB:?RESTORE_DB is required (must start with restore_)}"
: "${DRILL_OPERATOR:?DRILL_OPERATOR is required}"
DRILL_APPROVER="${DRILL_APPROVER:-}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"
RESTORE_JOBS="${RESTORE_JOBS:-2}"
CREATEDB="${CREATEDB:-createdb}"
# Default verification: the application image's restore_check against the restored database.
VERIFY_CMD="${VERIFY_CMD:-docker compose -f compose.prod.yml --env-file .env.prod run --rm -T -e POSTGRES_DB=$RESTORE_DB -e RUN_MIGRATIONS=0 backend python manage.py restore_check}"

case "$RESTORE_DB" in
  restore_*) ;;
  *) echo "Refusing: RESTORE_DB must start with 'restore_' (never restore over a live database)." >&2; exit 1 ;;
esac

umask 077
mkdir -p "$RECORD_DIR"
started_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
t0=$(date +%s)
record="$RECORD_DIR/drill-$(date -u +%Y%m%dT%H%M%SZ).json"
verify_out="$(mktemp)"
workdir="$(mktemp -d)"
chmod 700 "$workdir"
trap 'rm -f "$verify_out"; rm -rf "$workdir"' EXIT

fail() {
  echo "DRILL FAILED: $*" >&2
  printf '{"started_utc": "%s", "backup": "%s", "restore_db": "%s", "result": "failed", "reason": "%s", "operator": "%s", "approver": "%s"}\n' \
    "$started_utc" "$(basename "$BACKUP")" "$RESTORE_DB" "$*" "$DRILL_OPERATOR" "$DRILL_APPROVER" >"$record"
  echo "record: $record" >&2
  exit 1
}

[ -s "$BACKUP" ] || fail "backup file missing or empty"
[ -s "$BACKUP.sha256" ] || fail "checksum file $BACKUP.sha256 missing"
(cd "$(dirname "$BACKUP")" && sha256sum -c --status "$(basename "$BACKUP").sha256") || fail "sha256 mismatch"
sha=$(cut -d' ' -f1 "$BACKUP.sha256")
echo "checksum ok ($sha)"

$CREATEDB "$RESTORE_DB" || fail "could not create $RESTORE_DB (it must not exist yet)"
t_restore=$(date +%s)
gpg --batch --quiet --decrypt --output "$workdir/restore.dump" "$BACKUP" || fail "decryption failed (private key?)"
$PG_RESTORE --no-owner --no-privileges --exit-on-error --jobs "$RESTORE_JOBS" -d "$RESTORE_DB" "$workdir/restore.dump" \
  || fail "pg_restore failed"
rm -f "$workdir/restore.dump"
restore_seconds=$(( $(date +%s) - t_restore ))
echo "restored into $RESTORE_DB in ${restore_seconds}s"

if bash -c "$VERIFY_CMD" >"$verify_out"; then verified=true; else verified=false; fi
cat "$verify_out"

created_utc=""
[ -r "$BACKUP.json" ] && created_utc=$(sed -n 's/.*"created_utc": "\([^"]*\)".*/\1/p' "$BACKUP.json" | head -1)
{
  printf '{"started_utc": "%s", "ended_utc": "%s", "backup": "%s", "backup_created_utc": "%s", "sha256": "%s",\n' \
    "$started_utc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$BACKUP")" "$created_utc" "$sha"
  printf ' "restore_db": "%s", "restore_seconds": %s, "total_seconds": %s, "verified": %s,\n' \
    "$RESTORE_DB" "$restore_seconds" "$(( $(date +%s) - t0 ))" "$verified"
  printf ' "operator": "%s", "approver": "%s", "result": "%s",\n "verification": ' \
    "$DRILL_OPERATOR" "$DRILL_APPROVER" "$([ "$verified" = true ] && echo passed || echo failed)"
  if [ -s "$verify_out" ]; then cat "$verify_out"; else echo null; fi
  echo "}"
} >"$record"
echo "record: $record"
[ "$verified" = true ] || { echo "DRILL FAILED: verification failed" >&2; exit 1; }
echo "DRILL PASSED"
