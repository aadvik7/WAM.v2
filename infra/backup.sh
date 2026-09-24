#!/usr/bin/env bash
# Nightly Postgres backup (WAM + Chatwoot), kept BACKUP_KEEP_DAYS days locally and copied to
# separate storage with rclone when BACKUP_REMOTE is set. Cron example (02:30 IST = 21:00 UTC):
#   0 21 * * * /opt/wam/infra/backup.sh >> /var/log/wam-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

DEST="${BACKUP_DIR:-$(pwd)/backups}"
KEEP="${BACKUP_KEEP_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DEST"

for db in wam chatwoot; do
  file="$DEST/${db}-${STAMP}.dump"
  docker compose exec -T postgres pg_dump -U postgres -Fc "$db" > "$file.partial"
  mv "$file.partial" "$file"
  echo "$(date -u +%FT%TZ) backed up $db -> $file ($(du -h "$file" | cut -f1))"
done

find "$DEST" -name '*.dump' -mtime +"$KEEP" -delete

if [ -n "${BACKUP_REMOTE:-}" ]; then
  rclone copy "$DEST" "$BACKUP_REMOTE" --include "*-${STAMP}.dump"
  rclone delete "$BACKUP_REMOTE" --min-age "${KEEP}d" --include "*.dump" || true
  echo "copied to $BACKUP_REMOTE"
fi

if [ -n "${ALERT_WEBHOOK_URL:-}" ] && [ "${BACKUP_NOTIFY_SUCCESS:-false}" = "true" ]; then
  curl -fsS -X POST -H 'content-type: application/json' -d "{\"text\":\"[WAM] backup ${STAMP} ok\"}" "$ALERT_WEBHOOK_URL" >/dev/null || true
fi
