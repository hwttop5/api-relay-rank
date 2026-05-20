#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="手动刷新 Codex Manager 排名与质量数据。")
    parser.add_argument(
        "--capture-live-probes",
        action="store_true",
        help="刷新前先抓取当前已登录浏览器页的 live auth probe。",
    )
    args = parser.parse_args()

    steps: list[str] = []
    if args.capture_live_probes:
        run(["python", "capture_tabbit_live_probes.py"], cwd=APP_ROOT)
        steps.append("capture_tabbit_live_probes.py")

    run(["python", "audit_proxy_multipliers.py"], cwd=APP_ROOT)
    steps.append("audit_proxy_multipliers.py")

    run(["python", "scripts/build_site_data.py"], cwd=APP_ROOT)
    steps.append("scripts/build_site_data.py")

    print(json.dumps({"completed": steps}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
