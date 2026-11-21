# Backup sidecar: pg_dump (PostgreSQL 16 client) | age → Cloudflare R2 via rclone, every 6 h.
FROM alpine:3.22
RUN apk add --no-cache postgresql16-client age rclone bash curl coreutils tini \
 && adduser -D -u 10002 backup
COPY backup.sh restore.sh verify.sql /opt/backup/
USER backup
ENTRYPOINT ["/sbin/tini", "--"]
# First backup shortly after start, then every BACKUP_INTERVAL_SECONDS. A failed run logs and retries
# at the next interval; the BACKUP_PING_URL dead-man switch alerts if backups stop.
CMD ["bash", "-c", "sleep 120; while true; do /opt/backup/backup.sh || echo '{\"event\":\"backup.failed\"}'; sleep \"${BACKUP_INTERVAL_SECONDS:-21600}\"; done"]
