#!/usr/bin/env bash
set -euo pipefail

echo "Starting deployment..."
python manage.py migrate --noinput
python manage.py seed_permissions
python manage.py seed_roles
python manage.py collectstatic --noinput

echo "Deployment complete."
