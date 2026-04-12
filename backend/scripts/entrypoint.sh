#!/bin/sh
set -eu

python /app/scripts/wait_for_services.py
exec "$@"

