#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# These seed commands are idempotent and keep RBAC available after a fresh deployment.
python manage.py seed_permissions
python manage.py seed_roles

exec gunicorn AISchoolManagement.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - --error-logfile -
