#!/usr/bin/env bash
# Encrypted PostgreSQL backup (Phase 7, ADR 0007).
#   pg_dump (custom format) | age (public-key encryption) → Cloudflare R2 (or a local directory).
# The server only holds the age *recipient* (public key): a stolen server can't read old backups.
# Env: DATABASE_URL (owner role), AGE_RECIPIENT, BACKUP_TARGET=r2|local,
#      R2: RCLONE_CONFIG_R2_* + R2_BUCKET; local: BACKUP_DIR. Optional: BACKUP_PING_URL (dead-man switch).
set -euo pipefail
: "${DATABASE_URL:?}" "${AGE_RECIPIENT:?}"
TARGET="${BACKUP_TARGET:-r2}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
name="agentfirm-${ts}.dump.age"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

start=$(date +%s)
pg_dump --format=custom --compress=6 --no-password "$DATABASE_URL" | age -r "$AGE_RECIPIENT" -o "$tmp/$name"
sha256sum "$tmp/$name" | awk '{print $1}' > "$tmp/$name.sha256"
size=$(stat -c %s "$tmp/$name")

case "$TARGET" in
  r2)
    : "${R2_BUCKET:?}"
    rclone copyto "$tmp/$name" "r2:${R2_BUCKET}/postgres/daily/$name" --s3-no-check-bucket
    rclone copyto "$tmp/$name.sha256" "r2:${R2_BUCKET}/postgres/daily/$name.sha256" --s3-no-check-bucket
    # First backup of the month is also kept as a monthly copy.
    if [ "$(date -u +%d)" = "01" ] && ! rclone lsf "r2:${R2_BUCKET}/postgres/monthly/" | grep -q "agentfirm-$(date -u +%Y%m)"; then
      rclone copyto "$tmp/$name" "r2:${R2_BUCKET}/postgres/monthly/$name" --s3-no-check-bucket
    fi
    # Retention: daily 35 days, monthly 400 days.
    rclone delete "r2:${R2_BUCKET}/postgres/daily/" --min-age 35d
    rclone delete "r2:${R2_BUCKET}/postgres/monthly/" --min-age 400d
    ;;
  local)
    : "${BACKUP_DIR:?}"
    mkdir -p "$BACKUP_DIR"
    cp "$tmp/$name" "$tmp/$name.sha256" "$BACKUP_DIR/"
    find "$BACKUP_DIR" -name 'agentfirm-*.dump.age*' -mtime +35 -delete
    ;;
  *) echo "unknown BACKUP_TARGET=$TARGET" >&2; exit 2 ;;
esac

secs=$(( $(date +%s) - start ))
echo "{\"event\":\"backup.completed\",\"file\":\"$name\",\"bytes\":$size,\"seconds\":$secs,\"target\":\"$TARGET\"}"
[ -n "${BACKUP_PING_URL:-}" ] && curl -fsS -m 10 "$BACKUP_PING_URL" >/dev/null || true
