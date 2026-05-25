#!/bin/sh
set -eu

cd /app
python scripts/seed_runtime_data.py
python scripts/rebuild_runtime_site_data.py
exec supercronic /app/deploy/cron/refresh.cron
