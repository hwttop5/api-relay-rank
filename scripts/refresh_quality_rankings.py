#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]


def run(command: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=check)


def maybe_run_login_probe_refresh(steps: list[str]) -> None:
    if not os.environ.get("API_RELAY_SCRAPE_EMAIL") or not os.environ.get("API_RELAY_SCRAPE_PASSWORD"):
        steps.append("scripts/scrape_missing_announcements.py skipped (missing scrape credentials)")
        return
    result = run(["python", "scripts/scrape_missing_announcements.py", "--all-stations", "--write-probes"], cwd=APP_ROOT, check=False)
    if result.returncode == 0:
        steps.append("scripts/scrape_missing_announcements.py --all-stations --write-probes")
    else:
        steps.append(
            "scripts/scrape_missing_announcements.py --all-stations --write-probes "
            f"failed with exit {result.returncode}; preserved existing probes"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="手动刷新 Codex Manager 排名与质量数据。")
    parser.add_argument(
        "--capture-live-probes",
        action="store_true",
        help="刷新前先抓取当前已登录浏览器页的 live auth probe。",
    )
    parser.add_argument(
        "--full-log-rebuild",
        action="store_true",
        help=(
            "从 Codex Manager DB 全量重建日志累计状态。只有历史 request_logs 仍完整时才使用；"
            "旧日志已清理时保持默认增量模式。"
        ),
    )
    args = parser.parse_args()

    steps: list[str] = []
    if args.capture_live_probes:
        run(["python", "capture_tabbit_live_probes.py"], cwd=APP_ROOT)
        steps.append("capture_tabbit_live_probes.py")

    audit_command = ["python", "audit_proxy_multipliers.py"]
    if args.full_log_rebuild:
        audit_command.append("--full-log-rebuild")
    run(audit_command, cwd=APP_ROOT)
    steps.append("audit_proxy_multipliers.py")

    run(["python", "scripts/build_site_data.py"], cwd=APP_ROOT)
    steps.append("scripts/build_site_data.py")

    run(["python", "scripts/fetch_public_content.py", "--announcements", "--multiplier-snapshots", "--skip-build", "--quiet"], cwd=APP_ROOT)
    steps.append("scripts/fetch_public_content.py --skip-build")

    maybe_run_login_probe_refresh(steps)

    run(audit_command, cwd=APP_ROOT)
    steps.append("audit_proxy_multipliers.py (post-fetch)")

    run(["python", "scripts/build_site_data.py"], cwd=APP_ROOT)
    steps.append("scripts/build_site_data.py (post-fetch)")

    print(json.dumps({"completed": steps}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
