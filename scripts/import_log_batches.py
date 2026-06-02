#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.database import _jsonb, connect, ensure_database
    from scripts.runtime_paths import DATA_DIR
except ModuleNotFoundError:
    from database import _jsonb, connect, ensure_database
    from runtime_paths import DATA_DIR


SCHEMA_VERSION = 1
ALLOWED_LOG_FIELDS = {
    "id",
    "created_at",
    "request_type",
    "request_path",
    "aggregate_api_supplier_name",
    "aggregate_api_url",
    "status_code",
    "error",
    "duration_ms",
    "first_response_ms",
}

LOG_INBOX_DIR = Path(os.environ.get("LOG_INBOX_DIR", DATA_DIR / "log-inbox"))
LOG_ARCHIVE_DIR = Path(os.environ.get("LOG_ARCHIVE_DIR", DATA_DIR / "log-archive"))


@dataclass
class BatchPackage:
    path: Path
    manifest: dict[str, Any]
    rows: list[dict[str, Any]]
    jsonl_bytes: bytes


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def row_fingerprint(row: dict[str, Any]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_zip_member(package: zipfile.ZipFile, name: str) -> bytes:
    try:
        return package.read(name)
    except KeyError as exc:
        raise ValueError(f"Missing {name} in log batch.") from exc


def load_batch_package(path: Path) -> BatchPackage:
    with zipfile.ZipFile(path) as package:
        manifest_bytes = _read_zip_member(package, "manifest.json")
        jsonl_bytes = _read_zip_member(package, "request_logs.jsonl")

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must be a JSON object.")
    if int(manifest.get("schemaVersion") or 0) != SCHEMA_VERSION:
        raise ValueError(f"Unsupported log batch schemaVersion: {manifest.get('schemaVersion')}")
    batch_id = str(manifest.get("batchId") or "").strip()
    if not batch_id:
        raise ValueError("manifest.json missing batchId.")
    expected_hash = str(manifest.get("sha256") or "").strip().lower()
    actual_hash = sha256_bytes(jsonl_bytes)
    if expected_hash != actual_hash:
        raise ValueError("request_logs.jsonl sha256 does not match manifest.")

    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(jsonl_bytes.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"request_logs.jsonl line {line_no} is not an object.")
        unexpected = sorted(set(row) - ALLOWED_LOG_FIELDS)
        if unexpected:
            raise ValueError(f"request_logs.jsonl line {line_no} contains forbidden fields: {', '.join(unexpected)}")
        if row.get("id") is None or row.get("created_at") is None:
            raise ValueError(f"request_logs.jsonl line {line_no} missing id or created_at.")
        if row.get("request_type") != "http" or row.get("request_path") != "/v1/responses":
            raise ValueError(f"request_logs.jsonl line {line_no} is not an http /v1/responses row.")
        rows.append(row)

    if int(manifest.get("rowCount") or 0) != len(rows):
        raise ValueError("request_logs.jsonl row count does not match manifest.")
    return BatchPackage(path=path, manifest=manifest, rows=rows, jsonl_bytes=jsonl_bytes)


def archive_batch(path: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    if target.exists():
        target = archive_dir / f"{path.stem}-{sha256_bytes(path.read_bytes())[:8]}{path.suffix}"
    shutil.move(str(path), str(target))
    return target


def planned_archive_path(path: Path, archive_dir: Path) -> Path:
    target = archive_dir / path.name
    if target.exists():
        return archive_dir / f"{path.stem}-{sha256_bytes(path.read_bytes())[:8]}{path.suffix}"
    return target


def import_batch(package: BatchPackage, *, archive_path: Path | None = None) -> dict[str, Any]:
    ensure_database()
    batch_id = str(package.manifest["batchId"])
    inserted_rows = 0
    skipped_rows = 0

    with connect() as con:
        with con.cursor() as cur:
            cur.execute("select status from log_batches where batch_id = %s", (batch_id,))
            existing = cur.fetchone()
            if existing and existing[0] == "imported":
                con.commit()
                return {"batchId": batch_id, "status": "already_imported", "insertedRows": 0, "skippedRows": len(package.rows)}

            cur.execute(
                """
                insert into log_batches (
                  batch_id, schema_version, source_cursor, row_count, sha256, archive_path, status, manifest
                )
                values (%s, %s, %s, %s, %s, %s, 'importing', %s)
                on conflict (batch_id) do update
                set status = 'importing',
                    error = null,
                    archive_path = excluded.archive_path,
                    manifest = excluded.manifest
                """,
                (
                    batch_id,
                    int(package.manifest["schemaVersion"]),
                    _jsonb(package.manifest.get("sourceCursor") or {}),
                    len(package.rows),
                    str(package.manifest["sha256"]),
                    str(archive_path or ""),
                    _jsonb(package.manifest),
                ),
            )
            for row in package.rows:
                fingerprint = row_fingerprint(row)
                cur.execute(
                    """
                    insert into request_log_events (
                      batch_id,
                      source_id,
                      source_created_at,
                      request_type,
                      request_path,
                      aggregate_api_supplier_name,
                      aggregate_api_url,
                      status_code,
                      error,
                      duration_ms,
                      first_response_ms,
                      fingerprint
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (fingerprint) do nothing
                    """,
                    (
                        batch_id,
                        row.get("id"),
                        row.get("created_at"),
                        row.get("request_type"),
                        row.get("request_path"),
                        row.get("aggregate_api_supplier_name"),
                        row.get("aggregate_api_url"),
                        row.get("status_code"),
                        row.get("error"),
                        row.get("duration_ms"),
                        row.get("first_response_ms"),
                        fingerprint,
                    ),
                )
                if cur.rowcount:
                    inserted_rows += 1
                else:
                    skipped_rows += 1
            cur.execute(
                """
                update log_batches
                set status = 'imported',
                    imported_at = now(),
                    archive_path = %s,
                    error = null
                where batch_id = %s
                """,
                (str(archive_path or ""), batch_id),
            )
        con.commit()

    return {"batchId": batch_id, "status": "imported", "insertedRows": inserted_rows, "skippedRows": skipped_rows}


def sorted_batch_paths(inbox_dir: Path) -> list[Path]:
    if not inbox_dir.exists():
        return []
    return sorted(path for path in inbox_dir.glob("*.zip") if path.is_file())


def import_available_batches(*, inbox_dir: Path = LOG_INBOX_DIR, archive_dir: Path = LOG_ARCHIVE_DIR) -> dict[str, Any]:
    imported: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in sorted_batch_paths(inbox_dir):
        try:
            package = load_batch_package(path)
            result = import_batch(package, archive_path=planned_archive_path(path, archive_dir))
            archive_path = archive_batch(path, archive_dir)
            result["archivePath"] = str(archive_path)
            imported.append(result)
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"imported": imported, "errors": errors}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import sanitized Codex Manager log batches into PostgreSQL.")
    parser.add_argument("--inbox-dir", type=Path, default=LOG_INBOX_DIR)
    parser.add_argument("--archive-dir", type=Path, default=LOG_ARCHIVE_DIR)
    parser.add_argument("--fail-on-error", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = import_available_batches(inbox_dir=args.inbox_dir, archive_dir=args.archive_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.fail_on_error and result["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
