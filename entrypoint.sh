#!/bin/sh
set -e

echo "Waiting for PostgreSQL to be ready..."
until python - << 'PYCHECKEOF'
import psycopg2, os, sys
try:
    conn_kwargs = {
        "host": os.environ.get("POSTGRES_HOST", "postgres"),
        "port": os.environ.get("POSTGRES_PORT", "5432"),
        "dbname": os.environ.get("POSTGRES_DB", "industrial_ai"),
        "user": os.environ.get("POSTGRES_USER", "postgres"),
        "password": os.environ.get("POSTGRES_PASSWORD", "changeme"),
    }
    psycopg2.connect(**conn_kwargs)
    sys.exit(0)
except Exception:
    sys.exit(1)
PYCHECKEOF
do
    echo "  PostgreSQL not ready yet - retrying in 2s..."
    sleep 2
done
echo "PostgreSQL is ready."

exec uvicorn app.main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "${APP_PORT:-8000}" \
    --log-level "${LOG_LEVEL:-info}"
