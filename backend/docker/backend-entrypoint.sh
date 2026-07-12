#!/bin/sh
set -e

if [ -n "$DATABASE_URL" ]; then
    ALEMBIC_URL=$(echo "$DATABASE_URL" | sed 's|+asyncpg||')
    echo "Running alembic migrations…"
    DATABASE_URL="$ALEMBIC_URL" alembic upgrade head
fi

exec uvicorn dte.api.main:app --host 0.0.0.0 --port 8001
