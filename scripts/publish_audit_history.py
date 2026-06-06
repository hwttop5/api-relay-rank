#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.database import publish_station_audit_history
    from scripts.runtime_paths import AUDIT_RUNS_DIR
except ModuleNotFoundError:
    from database import publish_station_audit_history
    from runtime_paths import AUDIT_RUNS_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish archived station audit history metadata into PostgreSQL.")
    parser.add_argument("--audit-runs", type=Path, default=AUDIT_RUNS_DIR)
    parser.add_argument("--delete-missing", action="store_true", help="Remove database rows whose summary files are no longer retained.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = publish_station_audit_history(audit_runs_dir=args.audit_runs, delete_missing=args.delete_missing)
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
