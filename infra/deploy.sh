#!/usr/bin/env bash
# Build and (re)start the WAM stack. Safe to run repeatedly (e.g. after `git pull`).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Missing infra/.env — copy .env.example to .env and fill it in." >&2
  exit 1
fi
set -a; . ./.env; set +a
for var in POSTGRES_PASSWORD REDIS_PASSWORD WAM_DB_PASSWORD WAM_SECRET_KEY WAM_WEBHOOK_SECRET SECRET_KEY_BASE INBOX_DOMAIN API_DOMAIN ACME_EMAIL; do
  if [ -z "${!var:-}" ]; then echo "Set $var in infra/.env" >&2; exit 1; fi
done

docker compose pull postgres redis chatwoot caddy
docker compose build wam-core
docker compose up -d postgres redis

echo "Preparing Chatwoot database (creates or migrates)…"
docker compose run --rm chatwoot bundle exec rails db:chatwoot_prepare

echo "Applying WAM branding to the inbox…"
docker compose run --rm -e WAM_BRAND_URL="https://${INBOX_DOMAIN}" chatwoot bundle exec rails runner /wam/branding.rb || \
  echo "Branding step failed (non-fatal); rerun later with the same command."

docker compose up -d
docker compose ps
echo
echo "Done. Inbox: https://${INBOX_DOMAIN}   WAM API: https://${API_DOMAIN}/health"
echo "Chatwoot agent-bot webhook URL: https://${API_DOMAIN}/webhooks/chatwoot/${WAM_WEBHOOK_SECRET}"
