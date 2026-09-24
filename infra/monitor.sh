#!/usr/bin/env bash
# Alert if the webhook/API, job queue, WhatsApp sending or the inbox is unhealthy.
# Cron every 5 minutes:  */5 * * * * /opt/wam/infra/monitor.sh
set -uo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

problems=()
health="$(curl -fsS --max-time 10 "https://${API_DOMAIN}/health" 2>&1)" || problems+=("WAM core health failed: ${health:0:300}")
curl -fsS --max-time 10 -o /dev/null "https://${INBOX_DOMAIN}/" || problems+=("Inbox (Chatwoot) is not responding")
disk="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')"
[ "${disk:-0}" -lt 90 ] || problems+=("Disk ${disk}% full")

if [ ${#problems[@]} -gt 0 ]; then
  msg="[WAM] $(hostname): ${problems[*]}"
  echo "$(date -u +%FT%TZ) $msg"
  if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
    body="$(printf '%s' "$msg" | python3 -c 'import json,sys; t=sys.stdin.read(); print(json.dumps({"text": t, "content": t}))')"
    curl -fsS -X POST -H 'content-type: application/json' -d "$body" "$ALERT_WEBHOOK_URL" >/dev/null || true
  fi
  exit 1
fi
