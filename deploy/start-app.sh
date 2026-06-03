#!/bin/sh
set -eu

cd /app
python scripts/seed_runtime_data.py
python scripts/migrate_database.py
if [ "${SITE_DATA_SOURCE:-json}" = "postgres" ]; then
  python scripts/rebuild_runtime_site_data.py
  python scripts/publish_site_data_snapshot.py --source app-startup
fi
python scripts/refresh_owner_announcement.py || true
exec next start -H 0.0.0.0 -p "${PORT:-3000}"
