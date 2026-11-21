#!/usr/bin/env bash
# Restore an encrypted backup into an EMPTY database, then verify it (Phase 7 restore drill).
# Usage: restore.sh <backup file | r2:latest> <target DATABASE_URL (owner role)>
# Env: AGE_IDENTITY (path to the private key; kept offline, brought in only for a restore).
set -euo pipefail
src="${1:?backup file or r2:latest}"; target="${2:?target database url}"
: "${AGE_IDENTITY:?}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
here="$(cd "$(dirname "$0")" && pwd)"

if [ "$src" = "r2:latest" ]; then
  : "${R2_BUCKET:?}"
  latest="$(rclone lsf "r2:${R2_BUCKET}/postgres/daily/" --include 'agentfirm-*.dump.age' | sort | tail -1)"
  rclone copyto "r2:${R2_BUCKET}/postgres/daily/$latest" "$tmp/$latest"
  rclone copyto "r2:${R2_BUCKET}/postgres/daily/$latest.sha256" "$tmp/$latest.sha256"
  src="$tmp/$latest"
fi
if [ -f "$src.sha256" ]; then
  [ "$(sha256sum "$src" | awk '{print $1}')" = "$(cat "$src.sha256")" ] || { echo "checksum mismatch" >&2; exit 3; }
fi

t0=$(date +%s)
age -d -i "$AGE_IDENTITY" -o "$tmp/restore.dump" "$src"
t1=$(date +%s)
pg_restore --exit-on-error --no-owner --role="${RESTORE_ROLE:-agentfirm_owner}" --dbname="$target" "$tmp/restore.dump"
t2=$(date +%s)
psql "$target" -v ON_ERROR_STOP=1 -q -f "$here/verify.sql"
t3=$(date +%s)
echo "{\"event\":\"restore.completed\",\"decrypt_s\":$((t1-t0)),\"restore_s\":$((t2-t1)),\"verify_s\":$((t3-t2))}"
