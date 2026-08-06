#!/bin/sh

# Based on Temporal's official samples-server PostgreSQL setup flow.
set -eu

: "${POSTGRES_SEEDS:?POSTGRES_SEEDS is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PWD:?POSTGRES_PWD is required}"

PORT=${DB_PORT:-5432}
export SQL_PASSWORD="${SQL_PASSWORD:-$POSTGRES_PWD}"

nc -z -w 10 "$POSTGRES_SEEDS" "$PORT"

temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "$PORT" --db temporal create
temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "$PORT" --db temporal setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "$PORT" --db temporal update-schema \
  -d /etc/temporal/schema/postgresql/v12/temporal/versioned

temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "$PORT" --db temporal_visibility create
temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "$PORT" --db temporal_visibility setup-schema -v 0.0
temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "$PORT" --db temporal_visibility update-schema \
  -d /etc/temporal/schema/postgresql/v12/visibility/versioned
