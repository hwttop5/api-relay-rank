#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
WORKSPACE_ROOT = APP_ROOT.parents[0]
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", APP_ROOT / "data"))
SITE_DATA_PATH = DATA_DIR / "site-data.json"
PUBLIC_FETCH_DIR = Path(os.environ.get("PUBLIC_FETCH_DIR", DATA_DIR / "_public_fetch"))
AUDIT_RUNS_DIR = DATA_DIR / "_audit_runs"
USER_UPLOADS_DIR = DATA_DIR / "_user_uploads"
ERROR_REPORT_UPLOADS_DIR = USER_UPLOADS_DIR / "error-reports"
STATION_SUBMISSION_UPLOADS_DIR = USER_UPLOADS_DIR / "station-submissions"
OWNER_ANNOUNCEMENT_DIR = DATA_DIR / "_owner_announcement"
OWNER_ANNOUNCEMENT_MANIFEST_PATH = OWNER_ANNOUNCEMENT_DIR / "manifest.json"
OWNER_ANNOUNCEMENT_ASSETS_DIR = OWNER_ANNOUNCEMENT_DIR / "assets"
OWNER_ANNOUNCEMENT_STATUS_PATH = OWNER_ANNOUNCEMENT_DIR / "status.json"
PUBLIC_FETCH_DIRS = [PUBLIC_FETCH_DIR]
LIVE_AUTH_PROBE_DIR = Path(os.environ.get("LIVE_AUTH_PROBE_DIR", WORKSPACE_ROOT / "tabbit-audit-profile"))
PENDING_API_PROBE_PATH = LIVE_AUTH_PROBE_DIR / "pending-stations-api-probes.json"
LOCKS_DIR = DATA_DIR / "_locks"


class LockHeldError(RuntimeError):
    """Raised when a runtime lock is already held."""


@dataclass
class FileLock:
    name: str
    path: Path

    def release(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_FETCH_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    USER_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ERROR_REPORT_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    STATION_SUBMISSION_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OWNER_ANNOUNCEMENT_DIR.mkdir(parents=True, exist_ok=True)
    OWNER_ANNOUNCEMENT_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_AUTH_PROBE_DIR.mkdir(parents=True, exist_ok=True)
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)


def lock_path(name: str) -> Path:
    return LOCKS_DIR / f"{name}.lock"


def _lock_payload(name: str) -> str:
    return json.dumps(
        {
            "name": name,
            "pid": os.getpid(),
            "createdAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
        ensure_ascii=False,
        indent=2,
    )


def _lock_is_stale(path: Path, stale_seconds: int) -> bool:
    if stale_seconds <= 0:
        return False
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age_seconds >= stale_seconds


def acquire_lock(name: str, *, stale_seconds: int = 0) -> FileLock:
    ensure_runtime_dirs()
    path = lock_path(name)
    payload = _lock_payload(name)

    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            if stale_seconds > 0 and _lock_is_stale(path, stale_seconds):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise LockHeldError(f"Runtime lock '{name}' is already held.") from exc
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            return FileLock(name=name, path=path)


@contextmanager
def exclusive_lock(name: str, *, stale_seconds: int = 0) -> Iterator[FileLock]:
    lock = acquire_lock(name, stale_seconds=stale_seconds)
    try:
        yield lock
    finally:
        lock.release()


def logical_data_path(path: Path) -> str:
    resolved = path.resolve()
    data_root = DATA_DIR.resolve()
    try:
        relative = resolved.relative_to(data_root)
    except ValueError:
        try:
            return str(resolved.relative_to(APP_ROOT.resolve())).replace("\\", "/")
        except ValueError:
            return str(resolved).replace("\\", "/")
    return str(Path("data") / relative).replace("\\", "/")


def resolve_logical_data_path(logical_path: str) -> Path:
    normalized = str(logical_path or "").replace("\\", "/").strip()
    if not normalized:
        return DATA_DIR
    if normalized == "data":
        return DATA_DIR
    if normalized.startswith("data/"):
        return DATA_DIR / Path(normalized).relative_to("data")
    return APP_ROOT / Path(normalized)
