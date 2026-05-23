#!/bin/sh
set -eu

cd /app
python scripts/seed_runtime_data.py
exec supercronic /app/deploy/cron/refresh.cron
