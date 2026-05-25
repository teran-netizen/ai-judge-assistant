#!/bin/sh
set -e

echo "[entrypoint] Running alembic migrations..."
python -m alembic upgrade head
echo "[entrypoint] Migrations done."

exec "$@"
