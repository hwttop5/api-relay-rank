#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

try:
    from scripts.runtime_paths import APP_ROOT, ensure_runtime_dirs, exclusive_lock
except ModuleNotFoundError:
    from runtime_paths import APP_ROOT, ensure_runtime_dirs, exclusive_lock

try:
    from scripts.database import new_run_id, record_analysis_failure, start_analysis_run
except ModuleNotFoundError:
    from database import new_run_id, record_analysis_failure, start_analysis_run

try:
    from scripts.run_station_audit import prune_audit_runs
except ModuleNotFoundError:
    from run_station_audit import prune_audit_runs


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=APP_ROOT, check=check, text=True)


def has_scrape_credentials() -> bool:
    return bool(os.environ.get("API_RELAY_SCRAPE_EMAIL")) and bool(os.environ.get("API_RELAY_SCRAPE_PASSWORD"))


def postgres_site_data_enabled() -> bool:
    return process_env("SITE_DATA_SOURCE") == "postgres" and bool(os.environ.get("DATABASE_URL", "").strip())


def process_env(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def generated_at_now() -> str:
    china_standard_time = timezone(timedelta(hours=8))
    return datetime.now(UTC).astimezone(china_standard_time).strftime("%Y-%m-%d %H:%M:%S %z")


def main() -> int:
    ensure_runtime_dirs()
    steps: list[str] = []
    degraded = False
    removed: list[str] = []
    use_database = postgres_site_data_enabled()
    run_id = os.environ.get("ANALYSIS_RUN_ID", "").strip() or (new_run_id("server-refresh") if use_database else "")
    if run_id:
        os.environ["ANALYSIS_RUN_ID"] = run_id

    try:
        if use_database:
            start_analysis_run(run_id, summary={"source": "server-refresh", "siteDataSource": "postgres"})
            run(["python", "scripts/import_log_batches.py", "--fail-on-error"])
            steps.append("import_log_batches")

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
            generated_at = generated_at_now()
            os.environ["SITE_DATA_GENERATED_AT"] = generated_at
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

        if use_database:
            run(["python", "scripts/publish_site_data_snapshot.py", "--run-id", run_id, "--source", "server-refresh"])
            steps.append("publish_site_data_snapshot")
    except BaseException as exc:
        if use_database and run_id:
            try:
                record_analysis_failure(run_id, str(exc), summary={"source": "server-refresh", "completed": steps})
            except Exception:
                pass
        raise

    print(
        json.dumps(
            {
                "ok": True,
                "degraded": degraded,
                "runId": run_id or None,
                "generatedAt": generated_at,
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
