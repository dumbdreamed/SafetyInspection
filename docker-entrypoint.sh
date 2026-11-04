#!/bin/sh
set -eu

if [ -z "${DJANGO_SECRET_KEY:-}" ] || [ "${DJANGO_SECRET_KEY}" = "local-development-only-change-me" ]; then
  echo "DJANGO_SECRET_KEY is required. Add it as a private Hugging Face Space secret." >&2
  exit 1
fi

mkdir -p "${PERSISTENCE_DIR:-/data}/backups" "${MEDIA_ROOT:-/data/private-media}"
python manage.py check_persistence
python manage.py restore_db
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
python manage.py backup_db

exec gunicorn safetyinspection.wsgi:application \
  --bind "0.0.0.0:${PORT:-7860}" \
  --workers 1 \
  --threads 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
