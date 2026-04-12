#!/bin/sh
set -eu

python /app/manage.py migrate --noinput
python /app/manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  --max-requests 1000 \
  --max-requests-jitter 100

