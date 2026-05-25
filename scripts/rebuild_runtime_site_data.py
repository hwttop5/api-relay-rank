#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

try:
    from scripts.runtime_paths import APP_ROOT, SITE_DATA_PATH, LockHeldError, ensure_runtime_dirs, exclusive_lock, logical_data_path
except ModuleNotFoundError:
    from runtime_paths import APP_ROOT, SITE_DATA_PATH, LockHeldError, ensure_runtime_dirs, exclusive_lock, logical_data_path


GENERATED_AT_ENV = "SITE_DATA_GENERATED_AT"
LOCK_NAME = "site-data-rebuild"
LOCK_STALE_SECONDS = 60 * 60
LOCK_WAIT_SECONDS = 10 * 60
LOCK_RETRY_SECONDS = 5


def read_generated_at(path: Path | None = None) -> str:
    path = path or SITE_DATA_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    value = str(payload.get("generatedAt") or "").strip()
    return value


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=APP_ROOT, check=check, text=True)


def rebuild_with_lock() -> None:
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            with exclusive_lock(LOCK_NAME, stale_seconds=LOCK_STALE_SECONDS):
                run(["python", "scripts/build_site_data.py"])
            return
        except LockHeldError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(LOCK_RETRY_SECONDS)


def main() -> int:
    ensure_runtime_dirs()
    generated_at = read_generated_at()
    previous_generated_at = os.environ.get(GENERATED_AT_ENV)

    try:
        if generated_at:
            os.environ[GENERATED_AT_ENV] = generated_at
        rebuild_with_lock()
    finally:
        if previous_generated_at is None:
            os.environ.pop(GENERATED_AT_ENV, None)
        else:
            os.environ[GENERATED_AT_ENV] = previous_generated_at

    print(
        json.dumps(
            {
                "ok": True,
                "generatedAt": generated_at,
                "siteDataPath": logical_data_path(SITE_DATA_PATH),
                "lock": LOCK_NAME,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
