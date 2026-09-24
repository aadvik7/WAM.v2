#!/bin/sh
# Runs once, when the Postgres volume is first created. Chatwoot uses the `chatwoot` database
# (created by POSTGRES_DB); WAM gets its own role and database.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<SQL
CREATE ROLE wam LOGIN PASSWORD '${WAM_DB_PASSWORD}';
CREATE DATABASE wam OWNER wam;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname wam -c "CREATE EXTENSION IF NOT EXISTS btree_gist;"
