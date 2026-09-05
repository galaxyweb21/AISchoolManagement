#!/bin/sh
set -eu

cd /app

if [ "${WAIT_FOR_DB:-0}" = "1" ]; then
  echo "Waiting for database at ${DB_HOST:-db}:${DB_PORT:-3306}..."
  python - <<'PY'
import os, socket, time
host = os.getenv("DB_HOST", "db")
port = int(os.getenv("DB_PORT", "3306"))
for attempt in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            print("Database is reachable.")
            break
    except OSError:
        if attempt == 59:
            raise
        time.sleep(2)
PY
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "Applying database migrations..."
  python manage.py migrate --noinput
fi

# Ensure the fictional demo administrator exists after every deployment.
# This is idempotent and does not create an account for real school data.
if [ "${ENSURE_DEMO_ADMIN:-1}" = "1" ]; then
  echo "Ensuring demo administrator account..."
  python manage.py ensure_demo_admin
fi

if [ "${RUN_COLLECTSTATIC:-1}" = "1" ]; then
  echo "Collecting static files..."
  python manage.py collectstatic --noinput
fi

exec "$@"
