#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path

try:
    from scripts.runtime_paths import (
        APP_ROOT,
        AUDIT_RUNS_DIR,
        DATA_DIR,
        LIVE_AUTH_PROBE_DIR,
        LOCKS_DIR,
        PUBLIC_FETCH_DIR,
        SITE_DATA_PATH,
        ensure_runtime_dirs,
        logical_data_path,
    )
except ModuleNotFoundError:
    from runtime_paths import (
        APP_ROOT,
        AUDIT_RUNS_DIR,
        DATA_DIR,
        LIVE_AUTH_PROBE_DIR,
        LOCKS_DIR,
        PUBLIC_FETCH_DIR,
        SITE_DATA_PATH,
        ensure_runtime_dirs,
        logical_data_path,
    )

REPO_DATA_DIR = APP_ROOT / "data"
REPO_SITE_DATA_PATH = REPO_DATA_DIR / "site-data.json"
REPO_PUBLIC_FETCH_DIR = REPO_DATA_DIR / "_public_fetch"


def directory_has_entries(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def copy_tree_contents(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.iterdir():
        target_path = target_dir / source_path.name
        if source_path.is_dir():
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, target_path)


def main() -> int:
    ensure_runtime_dirs()
    seeded: dict[str, str] = {}

    if REPO_SITE_DATA_PATH.resolve() != SITE_DATA_PATH.resolve() and not SITE_DATA_PATH.exists() and REPO_SITE_DATA_PATH.exists():
        SITE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_SITE_DATA_PATH, SITE_DATA_PATH)
        seeded["siteData"] = logical_data_path(SITE_DATA_PATH)

    if (
        REPO_PUBLIC_FETCH_DIR.exists()
        and REPO_PUBLIC_FETCH_DIR.resolve() != PUBLIC_FETCH_DIR.resolve()
        and not directory_has_entries(PUBLIC_FETCH_DIR)
    ):
        copy_tree_contents(REPO_PUBLIC_FETCH_DIR, PUBLIC_FETCH_DIR)
        seeded["publicFetch"] = logical_data_path(PUBLIC_FETCH_DIR)

    print(
        json.dumps(
            {
                "ok": True,
                "seeded": seeded,
                "dataDir": str(DATA_DIR),
                "siteDataPath": str(SITE_DATA_PATH),
                "publicFetchDir": str(PUBLIC_FETCH_DIR),
                "auditRunsDir": str(AUDIT_RUNS_DIR),
                "liveAuthProbeDir": str(LIVE_AUTH_PROBE_DIR),
                "locksDir": str(LOCKS_DIR),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
