#!/bin/sh
set -eu

exec celery -A config beat --loglevel="${CELERY_LOG_LEVEL:-INFO}"

