#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    from scripts.database import new_run_id, publish_site_data_snapshot
    from scripts.runtime_paths import SITE_DATA_PATH
except ModuleNotFoundError:
    from database import new_run_id, publish_site_data_snapshot
    from runtime_paths import SITE_DATA_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish current site-data JSON into PostgreSQL.")
    parser.add_argument("--site-data", type=Path, default=SITE_DATA_PATH)
    parser.add_argument("--run-id", default=os.environ.get("ANALYSIS_RUN_ID", ""))
    parser.add_argument("--source", default="server-refresh")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id.strip() or new_run_id("manual-publish")
    payload = publish_site_data_snapshot(run_id=run_id, site_data_path=args.site_data, source=args.source)
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
