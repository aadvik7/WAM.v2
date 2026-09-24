#!/usr/bin/env bash
# Restore one database from a dump made by backup.sh. Test this before the pilot!
#   ./restore.sh wam backups/wam-20261001T210000Z.dump
#   ./restore.sh chatwoot backups/chatwoot-20261001T210000Z.dump
set -euo pipefail
cd "$(dirname "$0")"
db="${1:?database name: wam or chatwoot}"
file="${2:?path to .dump file}"
[ -f "$file" ] || { echo "No such file: $file" >&2; exit 1; }

read -r -p "This REPLACES the '$db' database with $file. Type the database name to continue: " answer
[ "$answer" = "$db" ] || { echo "Aborted."; exit 1; }

if [ "$db" = "wam" ]; then services="wam-core wam-worker"; else services="chatwoot chatwoot-sidekiq"; fi
docker compose stop $services
docker compose exec -T postgres pg_restore -U postgres --clean --if-exists --no-owner --role="$( [ "$db" = wam ] && echo wam || echo postgres )" -d "$db" < "$file"
docker compose start $services
echo "Restored $db from $file"
