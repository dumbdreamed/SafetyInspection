#!/bin/sh
set -eu

if [ -z "${DJANGO_SECRET_KEY:-}" ] || [ "${DJANGO_SECRET_KEY}" = "local-development-only-change-me" ]; then
  if [ "${PERSISTENCE_CONFIRMED:-0}" = "1" ]; then
    echo "DJANGO_SECRET_KEY is required when persistent storage is enabled." >&2
    exit 1
  fi
  DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
  export DJANGO_SECRET_KEY
  echo "Generated a temporary Django key; sessions will reset after a container restart."
fi

mkdir -p "${PERSISTENCE_DIR:-/tmp/safetyinspection-data}/backups" "${MEDIA_ROOT:-/tmp/safetyinspection-data/private-media}"
python manage.py check_persistence
if [ "${PERSISTENCE_CONFIRMED:-0}" = "1" ]; then
  python manage.py restore_db
else
  echo "Ephemeral storage mode: records and uploaded documents may be lost after a Space restart or rebuild."
fi
python manage.py migrate --noinput
python manage.py seed_reference_data

if [ -n "${BOOTSTRAP_ADMIN_USERNAME:-}" ]; then
  if [ -z "${BOOTSTRAP_ADMIN_PASSWORD:-}" ]; then
    echo "BOOTSTRAP_ADMIN_PASSWORD is required when BOOTSTRAP_ADMIN_USERNAME is set." >&2
    exit 1
  fi
  python manage.py bootstrap_admin
fi

python manage.py collectstatic --noinput
if [ "${PERSISTENCE_CONFIRMED:-0}" = "1" ]; then
  python manage.py backup_db
fi

exec gunicorn safetyinspection.wsgi:application \
  --bind "0.0.0.0:${PORT:-7860}" \
  --workers 1 \
  --threads 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
