#!/bin/sh
set -eu

cd /app
python scripts/seed_runtime_data.py
exec next start -H 0.0.0.0 -p "${PORT:-3000}"
