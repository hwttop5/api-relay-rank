#!/bin/sh
set -eu

cd /app
python scripts/seed_runtime_data.py
if [ "${SITE_DATA_SOURCE:-json}" = "postgres" ]; then
  python scripts/migrate_database.py
  python scripts/rebuild_runtime_site_data.py
  python scripts/publish_site_data_snapshot.py --source app-startup
  python scripts/publish_audit_history.py --delete-missing
else
  python scripts/rebuild_runtime_site_data.py
fi
python scripts/refresh_owner_announcement.py || true
exec next start -H 0.0.0.0 -p "${PORT:-3000}"
