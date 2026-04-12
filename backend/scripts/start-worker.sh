#!/bin/sh
set -eu

exec celery -A config worker --loglevel="${CELERY_LOG_LEVEL:-INFO}" --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"

