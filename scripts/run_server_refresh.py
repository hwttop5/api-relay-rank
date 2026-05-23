#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

try:
    from scripts.runtime_paths import APP_ROOT, ensure_runtime_dirs, exclusive_lock
except ModuleNotFoundError:
    from runtime_paths import APP_ROOT, ensure_runtime_dirs, exclusive_lock

try:
    from scripts.run_station_audit import prune_audit_runs
except ModuleNotFoundError:
    from run_station_audit import prune_audit_runs


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=APP_ROOT, check=check, text=True)


def has_scrape_credentials() -> bool:
    return bool(os.environ.get("API_RELAY_SCRAPE_EMAIL")) and bool(os.environ.get("API_RELAY_SCRAPE_PASSWORD"))


def main() -> int:
    ensure_runtime_dirs()
    steps: list[str] = []
    degraded = False

    run(["python", "scripts/fetch_public_content.py", "--announcements", "--multiplier-snapshots", "--skip-build"])
    steps.append("fetch_public_content")

    scrape_report_path = APP_ROOT / "output" / "server-refresh-live-auth-summary.json"
    scrape_report_path.parent.mkdir(parents=True, exist_ok=True)

    if has_scrape_credentials():
        with scrape_report_path.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                ["python", "scripts/scrape_missing_announcements.py", "--all-stations", "--write-probes"],
                cwd=APP_ROOT,
                check=False,
                text=True,
                stdout=handle,
            )
        if completed.returncode != 0:
            raise SystemExit(f"Live auth capture failed with exit {completed.returncode}.")
        steps.append("scrape_missing_announcements")
    else:
        degraded = True
        steps.append("scrape_missing_announcements skipped (missing scrape credentials)")

    with exclusive_lock("site-data-rebuild", stale_seconds=60 * 60):
        run(["python", "scripts/build_site_data.py"])
    steps.append("build_site_data")

    validate_command = ["python", "scripts/validate_refresh_outputs.py"]
    if has_scrape_credentials():
        validate_command.extend(["--scrape-report", str(scrape_report_path)])
    else:
        validate_command.append("--skip-scrape-validation")
    run(validate_command)
    steps.append("validate_refresh_outputs")

    removed = prune_audit_runs()
    steps.append(f"prune_audit_runs removed={len(removed)}")

    print(
        json.dumps(
            {
                "ok": True,
                "degraded": degraded,
                "completed": steps,
                "removedAuditRuns": removed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
