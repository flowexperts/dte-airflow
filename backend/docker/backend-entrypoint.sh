#!/bin/sh
set -e

# A custom command (e.g. `python -m dte.worker`) runs as-is. Without this the
# hardcoded `exec uvicorn` below silently swallowed compose's `command:` and
# the worker service came up as a second API replica.
#
# Migrations are skipped on that path on purpose: the `backend` service owns
# schema upgrades, and workers already wait on its healthcheck.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

if [ -n "$DTE_DATABASE_URL" ]; then
    ALEMBIC_URL=$(echo "$DTE_DATABASE_URL" | sed 's|+asyncpg||')
    echo "Running alembic migrations…"
    DTE_DATABASE_URL="$ALEMBIC_URL" alembic upgrade head
fi

exec uvicorn dte.api.main:app --host 0.0.0.0 --port 8001
