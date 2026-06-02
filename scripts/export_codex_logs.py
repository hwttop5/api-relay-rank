#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


SCHEMA_VERSION = 1
DEFAULT_DB_PATH = Path(os.environ.get("APPDATA", "")) / "com.codexmanager.desktop" / "codexmanager.db"
DEFAULT_OUTPUT_DIR = Path(os.environ.get("CODEX_LOG_EXPORT_DIR", Path.cwd() / ".local-artifacts" / "codex-log-batches"))

EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._~+\-/=]+", re.IGNORECASE)
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = EMAIL_PATTERN.sub("xxx", text)
    text = BEARER_PATTERN.sub("Bearer <redacted>", text)
    text = JWT_PATTERN.sub("xxx", text)
    text = SK_PATTERN.sub("sk-<redacted>", text)
    return text


def sanitize_url(value: Any) -> str:
    text = redact_text(value).strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return text
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", "")).rstrip("/")


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def row_to_public_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": as_int(row["id"]),
        "created_at": as_int(row["created_at"]),
        "request_type": str(row["request_type"] or ""),
        "request_path": str(row["request_path"] or ""),
        "aggregate_api_supplier_name": redact_text(row["aggregate_api_supplier_name"]),
        "aggregate_api_url": sanitize_url(row["aggregate_api_url"]),
        "status_code": as_int(row["status_code"]),
        "error": redact_text(row["error"]),
        "duration_ms": as_int(row["duration_ms"]),
        "first_response_ms": as_int(row["first_response_ms"]),
    }


def query_rows(db_path: Path, *, since_created_at: int | None = None) -> list[dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Codex Manager DB not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        query = """
            select id,
                   request_type,
                   request_path,
                   aggregate_api_supplier_name,
                   aggregate_api_url,
                   status_code,
                   error,
                   duration_ms,
                   first_response_ms,
                   created_at
            from request_logs
            where request_type = 'http'
              and request_path = '/v1/responses'
              and (aggregate_api_supplier_name is not null or aggregate_api_url is not null)
        """
        params: list[Any] = []
        if since_created_at is not None:
            query += " and created_at >= ?"
            params.append(since_created_at)
        query += " order by created_at, id"
        return [row_to_public_dict(row) for row in con.execute(query, params)]
    finally:
        con.close()


def source_cursor(rows: list[dict[str, Any]]) -> dict[str, int | None]:
    if not rows:
        return {"createdAt": None, "id": None}
    latest = max(rows, key=lambda row: (as_int(row.get("created_at")) or -1, as_int(row.get("id")) or -1))
    return {"createdAt": as_int(latest.get("created_at")), "id": as_int(latest.get("id"))}


def write_log_batch(rows: list[dict[str, Any]], output_dir: Path, *, batch_id: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    batch_id = batch_id or f"codex-log-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    jsonl_text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    jsonl_bytes = jsonl_text.encode("utf-8")
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "batchId": batch_id,
        "createdAt": created_at,
        "sourceCursor": source_cursor(rows),
        "rowCount": len(rows),
        "sha256": sha256_bytes(jsonl_bytes),
    }
    target = output_dir / f"{batch_id}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        package.writestr("request_logs.jsonl", jsonl_bytes)
    return target


def split_upload_target(target: str) -> tuple[str, str]:
    if ":" not in target:
        raise ValueError("Upload target must look like user@host:/remote/dir")
    host, remote_dir = target.split(":", 1)
    host = host.strip()
    remote_dir = remote_dir.strip().rstrip("/")
    if not host or not remote_dir:
        raise ValueError("Upload target must include both host and remote directory.")
    return host, remote_dir


def upload_with_scp(package_path: Path, target: str, *, identity_file: str = "") -> None:
    host, remote_dir = split_upload_target(target)
    ssh_base = ["ssh"]
    scp_base = ["scp"]
    if identity_file:
        ssh_base.extend(["-i", identity_file])
        scp_base.extend(["-i", identity_file])
    remote_tmp = f"{remote_dir}/{package_path.name}.tmp"
    remote_final = f"{remote_dir}/{package_path.name}"
    subprocess.run(ssh_base + [host, f"mkdir -p {shlex.quote(remote_dir)}"], check=True)
    subprocess.run(scp_base + [str(package_path), f"{host}:{remote_tmp}"], check=True)
    subprocess.run(ssh_base + [host, f"mv {shlex.quote(remote_tmp)} {shlex.quote(remote_final)}"], check=True)


def parse_args() -> argparse.Namespace:
    default_since = os.environ.get("CODEX_LOG_EXPORT_SINCE_CREATED_AT")
    parser = argparse.ArgumentParser(description="Export sanitized Codex Manager /v1/responses logs.")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("CODEX_MANAGER_DB_PATH", DEFAULT_DB_PATH)))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--since-created-at", type=int, default=int(default_since) if default_since else None)
    parser.add_argument("--upload-target", default=os.environ.get("CODEX_LOG_UPLOAD_TARGET", ""))
    parser.add_argument("--ssh-identity", default=os.environ.get("CODEX_LOG_SSH_IDENTITY", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = query_rows(args.db, since_created_at=args.since_created_at)
    package_path = write_log_batch(rows, args.output_dir)
    uploaded = False
    if args.upload_target:
        upload_with_scp(package_path, args.upload_target, identity_file=args.ssh_identity)
        uploaded = True
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(package_path),
                "rows": len(rows),
                "sourceCursor": source_cursor(rows),
                "uploaded": uploaded,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
