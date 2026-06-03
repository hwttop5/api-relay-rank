#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_paths import SITE_DATA_PATH
except ModuleNotFoundError:
    from runtime_paths import SITE_DATA_PATH


MIGRATION_VERSION = 1
DATABASE_URL_ENV = "DATABASE_URL"
REQUIRED_RANKING_COUNTS = {
    "all_hours": 39,
    "work_hours": 32,
    "off_hours": 38,
}
KEY_STATION_MIN_CORRECT_RATES = {
    ("nexus", "all_hours"): 0.95,
    ("nexus", "work_hours"): 0.95,
    ("zhima", "all_hours"): 0.95,
    ("zhima", "work_hours"): 0.95,
}


SCHEMA_SQL = """
create table if not exists log_batches (
  batch_id text primary key,
  schema_version integer not null,
  source_cursor jsonb not null default '{}'::jsonb,
  row_count integer not null default 0,
  sha256 text not null,
  archive_path text,
  status text not null,
  manifest jsonb not null,
  error text,
  created_at timestamptz not null default now(),
  imported_at timestamptz
);

create table if not exists request_log_events (
  id bigserial primary key,
  batch_id text not null references log_batches(batch_id) on delete cascade,
  source_id bigint,
  source_created_at bigint not null,
  request_type text,
  request_path text,
  aggregate_api_supplier_name text,
  aggregate_api_url text,
  status_code integer,
  error text,
  duration_ms integer,
  first_response_ms integer,
  fingerprint text not null unique,
  inserted_at timestamptz not null default now()
);

create index if not exists request_log_events_created_idx
  on request_log_events (source_created_at, source_id);
create index if not exists request_log_events_path_idx
  on request_log_events (request_path);

create table if not exists analysis_runs (
  run_id text primary key,
  status text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  summary jsonb not null default '{}'::jsonb,
  error text
);

create table if not exists quality_metrics (
  run_id text not null references analysis_runs(run_id) on delete cascade,
  station text not null,
  time_window text not null,
  payload jsonb not null,
  primary key (run_id, station, time_window)
);

create table if not exists ranking_rows (
  run_id text not null references analysis_runs(run_id) on delete cascade,
  station text not null,
  time_window text not null,
  rank integer,
  payload jsonb not null,
  primary key (run_id, station, time_window)
);

create table if not exists evidence_snapshots (
  id bigserial primary key,
  run_id text not null references analysis_runs(run_id) on delete cascade,
  station text,
  kind text not null,
  source_path text,
  status text,
  content_hash text,
  payload jsonb not null,
  captured_at timestamptz not null default now()
);

create index if not exists evidence_snapshots_run_idx
  on evidence_snapshots (run_id, station, kind);

create table if not exists site_data_snapshots (
  id bigserial primary key,
  run_id text not null references analysis_runs(run_id) on delete cascade,
  status text not null,
  generated_at text,
  payload jsonb,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists site_data_snapshots_latest_success_idx
  on site_data_snapshots (created_at desc, id desc)
  where status = 'success';
"""


class SnapshotValidationError(ValueError):
    pass


def database_url(*, required: bool = True) -> str | None:
    value = os.environ.get(DATABASE_URL_ENV, "").strip()
    if value:
        return value
    if required:
        raise RuntimeError(f"{DATABASE_URL_ENV} is required for PostgreSQL-backed site data.")
    return None


def _psycopg() -> Any:
    import psycopg

    return psycopg


def _jsonb(value: Any) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def connect(dsn: str | None = None) -> Any:
    return _psycopg().connect(dsn or database_url(), autocommit=False)


def ensure_database(dsn: str | None = None) -> None:
    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(772951418)")
            cur.execute(
                """
                create table if not exists schema_migrations (
                  version integer primary key,
                  applied_at timestamptz not null default now()
                )
                """
            )
            cur.execute("select 1 from schema_migrations where version = %s", (MIGRATION_VERSION,))
            if cur.fetchone() is None:
                cur.execute(SCHEMA_SQL)
                cur.execute("insert into schema_migrations (version) values (%s)", (MIGRATION_VERSION,))
        con.commit()


def new_run_id(prefix: str = "refresh") -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


def start_analysis_run(run_id: str, *, summary: dict[str, Any] | None = None, dsn: str | None = None) -> None:
    ensure_database(dsn)
    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute(
                """
                insert into analysis_runs (run_id, status, summary)
                values (%s, 'running', %s)
                on conflict (run_id) do update
                set status = excluded.status,
                    summary = excluded.summary,
                    error = null
                """,
                (run_id, _jsonb(summary or {})),
            )
        con.commit()


def record_analysis_failure(run_id: str, error: str, *, summary: dict[str, Any] | None = None, dsn: str | None = None) -> None:
    ensure_database(dsn)
    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute(
                """
                insert into analysis_runs (run_id, status, finished_at, summary, error)
                values (%s, 'failed', now(), %s, %s)
                on conflict (run_id) do update
                set status = 'failed',
                    finished_at = now(),
                    summary = excluded.summary,
                    error = excluded.error
                """,
                (run_id, _jsonb(summary or {}), error[:4000]),
            )
            cur.execute(
                """
                insert into site_data_snapshots (run_id, status, error)
                values (%s, 'failed', %s)
                """,
                (run_id, error[:4000]),
            )
        con.commit()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object.")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _ranking_counts(site_data: dict[str, Any]) -> dict[str, int]:
    rankings = site_data.get("rankings") if isinstance(site_data.get("rankings"), dict) else {}
    return {
        time_window: len(rows) if isinstance(rows, list) else 0
        for time_window, rows in rankings.items()
    }


def validate_site_data_snapshot(site_data: dict[str, Any]) -> dict[str, Any]:
    stations = site_data.get("stations")
    rankings = site_data.get("rankings")
    if not isinstance(stations, list) or not stations:
        raise SnapshotValidationError("site-data snapshot must include non-empty stations.")
    if not isinstance(rankings, dict):
        raise SnapshotValidationError("site-data snapshot must include rankings.")

    ranking_counts = _ranking_counts(site_data)
    for time_window, minimum in REQUIRED_RANKING_COUNTS.items():
        actual = ranking_counts.get(time_window, 0)
        if actual < minimum:
            raise SnapshotValidationError(f"{time_window} ranking rows regressed: expected >= {minimum}, got {actual}.")

    station_by_key = {
        str(station.get("key") or ""): station
        for station in stations
        if isinstance(station, dict)
    }
    for (station_key, time_window), minimum_rate in KEY_STATION_MIN_CORRECT_RATES.items():
        station = station_by_key.get(station_key)
        if not station:
            raise SnapshotValidationError(f"Missing key station: {station_key}.")
        quality = station.get("quality") if isinstance(station.get("quality"), dict) else {}
        metric = quality.get(time_window) if isinstance(quality.get(time_window), dict) else {}
        actual_rate = metric.get("correctRate")
        if not isinstance(actual_rate, (int, float)) or actual_rate < minimum_rate:
            raise SnapshotValidationError(
                f"{station_key} {time_window} correctRate regressed: expected >= {minimum_rate}, got {actual_rate}."
            )

    return {
        "stationCount": len(stations),
        "rankingCounts": ranking_counts,
    }


def publish_site_data_snapshot(
    *,
    run_id: str,
    site_data_path: Path = SITE_DATA_PATH,
    source: str = "server-refresh",
    dsn: str | None = None,
) -> dict[str, Any]:
    ensure_database(dsn)
    site_data = read_json(site_data_path)
    validation = validate_site_data_snapshot(site_data)
    generated_at = str(site_data.get("generatedAt") or "")
    ranking_count = 0
    quality_count = 0
    evidence_count = 0

    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute(
                """
                insert into analysis_runs (run_id, status, finished_at, summary)
                values (%s, 'success', now(), %s)
                on conflict (run_id) do update
                set status = 'success',
                    finished_at = now(),
                    summary = excluded.summary,
                    error = null
                """,
                (
                    run_id,
                    _jsonb(
                        {
                            "source": source,
                            "generatedAt": generated_at,
                            **validation,
                        }
                    ),
                ),
            )
            cur.execute("delete from quality_metrics where run_id = %s", (run_id,))
            cur.execute("delete from ranking_rows where run_id = %s", (run_id,))
            cur.execute("delete from evidence_snapshots where run_id = %s", (run_id,))

            rankings = site_data.get("rankings") if isinstance(site_data.get("rankings"), dict) else {}
            for time_window, rows in rankings.items():
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    station = str(row.get("station") or "")
                    cur.execute(
                        """
                        insert into ranking_rows (run_id, station, time_window, rank, payload)
                        values (%s, %s, %s, %s, %s)
                        on conflict (run_id, station, time_window) do update
                        set rank = excluded.rank,
                            payload = excluded.payload
                        """,
                        (run_id, station, str(time_window), row.get("rank"), _jsonb(row)),
                    )
                    ranking_count += 1

            for station in site_data.get("stations", []):
                if not isinstance(station, dict):
                    continue
                station_key = str(station.get("key") or "")
                quality = station.get("quality") if isinstance(station.get("quality"), dict) else {}
                for time_window, payload in quality.items():
                    if not isinstance(payload, dict):
                        continue
                    cur.execute(
                        """
                        insert into quality_metrics (run_id, station, time_window, payload)
                        values (%s, %s, %s, %s)
                        on conflict (run_id, station, time_window) do update
                        set payload = excluded.payload
                        """,
                        (run_id, station_key, str(time_window), _jsonb(payload)),
                    )
                    quality_count += 1
                for item in station.get("dataEvidence", []):
                    if not isinstance(item, dict):
                        continue
                    cur.execute(
                        """
                        insert into evidence_snapshots (run_id, station, kind, source_path, status, payload)
                        values (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            run_id,
                            station_key,
                            str(item.get("key") or "unknown"),
                            str(item.get("source") or ""),
                            str(item.get("status") or ""),
                            _jsonb(item),
                        ),
                    )
                    evidence_count += 1

            cur.execute(
                """
                insert into site_data_snapshots (run_id, status, generated_at, payload)
                values (%s, 'success', %s, %s)
                """,
                (run_id, generated_at, _jsonb(site_data)),
            )
        con.commit()

    return {
        "runId": run_id,
        "generatedAt": generated_at,
        "stationCount": validation["stationCount"],
        "rankingCounts": validation["rankingCounts"],
        "rankingRows": ranking_count,
        "qualityRows": quality_count,
        "evidenceRows": evidence_count,
    }
