#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
CONFIG_PATH = APP_ROOT / "config" / "task_config.json"


def load_jobs() -> list[dict[str, Any]]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else []
    return [job for job in jobs if isinstance(job, dict)]


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    command = [str(item) for item in job.get("command", [])]
    subprocess.run(command, cwd=APP_ROOT, check=True)
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "enabled": bool(job.get("enabled")),
        "autoRun": bool(job.get("autoRun")),
        "schedule": job.get("schedule"),
        "command": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="查看或执行中转站监视者任务配置。")
    parser.add_argument("--run-enabled", action="store_true", help="执行所有 enabled=true 的任务。")
    parser.add_argument("--job", help="执行指定任务 id。")
    parser.add_argument("--force-disabled", action="store_true", help="允许执行被禁用的任务。")
    args = parser.parse_args()

    jobs = load_jobs()
    by_id = {str(job.get("id")): job for job in jobs}

    if args.job:
        job = by_id.get(args.job)
        if not job:
            raise SystemExit(f"Unknown job id: {args.job}")
        if not job.get("enabled") and not args.force_disabled:
            raise SystemExit(f"Job {args.job} is disabled. Use --force-disabled to run it.")
        result = run_job(job)
        print(json.dumps({"executed": [result]}, ensure_ascii=False, indent=2))
        return 0

    if args.run_enabled:
        executed = [run_job(job) for job in jobs if job.get("enabled")]
        print(json.dumps({"executed": executed}, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
