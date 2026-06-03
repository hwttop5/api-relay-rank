#!/bin/sh
set -eu

cd /app
python scripts/seed_runtime_data.py
if [ "${SITE_DATA_SOURCE:-json}" = "postgres" ]; then
  python scripts/migrate_database.py
  python scripts/rebuild_runtime_site_data.py
  python scripts/publish_site_data_snapshot.py --source scheduler-startup
else
  python scripts/rebuild_runtime_site_data.py
fi
python scripts/refresh_owner_announcement.py || true
exec supercronic /app/deploy/cron/refresh.cron
