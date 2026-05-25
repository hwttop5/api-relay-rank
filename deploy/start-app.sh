#!/bin/sh
set -eu

cd /app
python scripts/seed_runtime_data.py
python scripts/rebuild_runtime_site_data.py
exec next start -H 0.0.0.0 -p "${PORT:-3000}"
