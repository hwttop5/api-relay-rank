#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    from scripts.database import SITE_TOTAL_IMPORT_PATH, _jsonb, connect, database_url, ensure_database
    from scripts.runtime_paths import APP_ROOT
except ModuleNotFoundError:
    from database import SITE_TOTAL_IMPORT_PATH, _jsonb, connect, database_url, ensure_database
    from runtime_paths import APP_ROOT


BASELINES_PATH = APP_ROOT / "config" / "page_view_baselines.json"

PATH_COLUMNS = {
    "页面 URL",
    "页面URL",
    "受访页面",
    "入口页面",
    "url",
    "URL",
    "path",
    "Path",
    "页面",
}
PV_COLUMNS = {"浏览量(PV)", "浏览量（PV）", "PV", "pv", "pv_count", "浏览量"}
UV_COLUMNS = {"访客数(UV)", "访客数（UV）", "UV", "uv", "visitor_count", "访客数"}


@dataclass(frozen=True)
class NormalizedPath:
    canonical_path: str
    station_key: str | None


@dataclass(frozen=True)
class ImportRow:
    source: str
    period_start: str
    period_end: str
    canonical_path: str
    station_key: str | None
    pv_count: int
    visitor_count: int | None
    metadata: dict[str, Any]


def parse_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def parse_count(value: Any) -> int:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0
    return max(0, int(float(text)))


def first_present(fieldnames: list[str], candidates: set[str]) -> str | None:
    exact = [name for name in fieldnames if name in candidates]
    if exact:
        return exact[0]
    normalized_candidates = {normalize_header(name): name for name in candidates}
    for name in fieldnames:
        candidate = normalized_candidates.get(normalize_header(name))
        if candidate:
            return name
    return None


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_()（）]+", "", value).lower()


def normalize_page_path(value: Any) -> NormalizedPath | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        path = parsed.path
    else:
        path = re.split(r"[?#]", text, maxsplit=1)[0]

    if not path.startswith("/"):
        return None
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")

    lower_path = path.lower()
    if lower_path == "/":
        return NormalizedPath("/ranking", None)
    if lower_path in {"/ranking", "/audit", "/statement"}:
        return NormalizedPath(lower_path, None)
    if lower_path == "/api" or lower_path.startswith("/api/") or lower_path.startswith("/_next/"):
        return None
    station_match = re.fullmatch(r"/stations/([^/]+)", path)
    if station_match:
        station_key = unquote(station_match.group(1))
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", station_key):
            return None
        return NormalizedPath(f"/stations/{station_key}", station_key)
    if re.search(r"\.[A-Za-z0-9]{1,8}$", path):
        return None
    return None


def csv_import_rows(path: Path, *, source: str, period_start: str, period_end: str) -> tuple[list[ImportRow], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        path_column = first_present(fieldnames, PATH_COLUMNS)
        pv_column = first_present(fieldnames, PV_COLUMNS)
        uv_column = first_present(fieldnames, UV_COLUMNS)
        if not path_column or not pv_column:
            raise ValueError("CSV must include a page URL/path column and a PV column.")

        aggregated: dict[str, ImportRow] = {}
        skipped: list[dict[str, Any]] = []
        for index, row in enumerate(reader, start=2):
            normalized = normalize_page_path(row.get(path_column))
            pv_count = parse_count(row.get(pv_column))
            visitor_count = parse_count(row.get(uv_column)) if uv_column else None
            if not normalized or pv_count <= 0:
                skipped.append({"line": index, "path": row.get(path_column), "pvCount": pv_count})
                continue
            existing = aggregated.get(normalized.canonical_path)
            metadata = {"sourceFile": path.name}
            if existing:
                aggregated[normalized.canonical_path] = ImportRow(
                    source=existing.source,
                    period_start=existing.period_start,
                    period_end=existing.period_end,
                    canonical_path=existing.canonical_path,
                    station_key=existing.station_key,
                    pv_count=existing.pv_count + pv_count,
                    visitor_count=(existing.visitor_count or 0) + (visitor_count or 0) if existing.visitor_count is not None or visitor_count is not None else None,
                    metadata=existing.metadata,
                )
            else:
                aggregated[normalized.canonical_path] = ImportRow(
                    source=source,
                    period_start=period_start,
                    period_end=period_end,
                    canonical_path=normalized.canonical_path,
                    station_key=normalized.station_key,
                    pv_count=pv_count,
                    visitor_count=visitor_count,
                    metadata=metadata,
                )
    return list(aggregated.values()), skipped


def total_import_row(
    *,
    source: str,
    period_start: str,
    period_end: str,
    total_pv: int,
    visitor_count: int | None,
    metadata: dict[str, Any],
) -> ImportRow:
    return ImportRow(
        source=source,
        period_start=period_start,
        period_end=period_end,
        canonical_path=SITE_TOTAL_IMPORT_PATH,
        station_key=None,
        pv_count=total_pv,
        visitor_count=visitor_count,
        metadata=metadata,
    )


def write_import_rows(rows: list[ImportRow]) -> None:
    ensure_database()
    with connect(database_url()) as con:
        with con.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    insert into page_view_import_rows (
                      source, period_start, period_end, canonical_path, station_key, pv_count, visitor_count, metadata
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (source, period_start, period_end, canonical_path) do update
                    set station_key = excluded.station_key,
                        pv_count = excluded.pv_count,
                        visitor_count = excluded.visitor_count,
                        metadata = excluded.metadata,
                        imported_at = now()
                    """,
                    (
                        row.source,
                        row.period_start,
                        row.period_end,
                        row.canonical_path,
                        row.station_key,
                        row.pv_count,
                        row.visitor_count,
                        _jsonb(row.metadata),
                    ),
                )
        con.commit()


def update_baseline_config(rows: list[ImportRow]) -> None:
    existing: list[dict[str, Any]] = []
    if BASELINES_PATH.exists():
        try:
            payload = json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                existing = [item for item in payload if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            existing = []

    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in existing:
        key = (
            str(item.get("source") or "baidu"),
            str(item.get("periodStart") or ""),
            str(item.get("periodEnd") or ""),
            str(item.get("canonicalPath") or ""),
        )
        by_key[key] = item
    for row in rows:
        key = (row.source, row.period_start, row.period_end, row.canonical_path)
        by_key[key] = {
            "source": row.source,
            "periodStart": row.period_start,
            "periodEnd": row.period_end,
            "canonicalPath": row.canonical_path,
            "stationKey": row.station_key,
            "pvCount": row.pv_count,
            "visitorCount": row.visitor_count,
            "metadata": row.metadata,
        }
    BASELINES_PATH.write_text(json.dumps(list(by_key.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(rows: list[ImportRow], skipped: list[dict[str, Any]], *, write: bool, baseline_config: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "write": write,
        "baselineConfig": baseline_config,
        "rows": len(rows),
        "skipped": len(skipped),
        "totalPv": sum(row.pv_count for row in rows if row.canonical_path == SITE_TOTAL_IMPORT_PATH)
        or sum(row.pv_count for row in rows),
        "stationPageRows": sum(1 for row in rows if row.station_key),
        "stationPagePv": sum(row.pv_count for row in rows if row.station_key),
        "periods": sorted({f"{row.period_start}..{row.period_end}" for row in rows}),
        "skippedSamples": skipped[:10],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import page-view history from Baidu Tongji CSV or total overview metrics.")
    parser.add_argument("--source", default="baidu", choices=["baidu"])
    parser.add_argument("--csv", type=Path, help="Baidu Tongji visited-page CSV export.")
    parser.add_argument("--start-date", required=True, help="Inclusive period start, YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Inclusive period end, YYYY-MM-DD.")
    parser.add_argument("--total-pv", type=int, help="Total site PV from Baidu overview.")
    parser.add_argument("--visitor-count", type=int, help="Optional total UV/visitor count.")
    parser.add_argument("--ip-count", type=int, help="Optional total IP count stored as metadata.")
    parser.add_argument("--bounce-rate", help="Optional bounce rate stored as metadata, e.g. 55.48%.")
    parser.add_argument("--average-visit-duration", help="Optional average visit duration stored as metadata, e.g. 00:05:30.")
    parser.add_argument("--write", action="store_true", help="Write rows into PostgreSQL.")
    parser.add_argument("--baseline-config", action="store_true", help="Also upsert rows into config/page_view_baselines.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    period_start = parse_date(args.start_date)
    period_end = parse_date(args.end_date)
    rows: list[ImportRow] = []
    skipped: list[dict[str, Any]] = []

    if args.csv:
        csv_rows, csv_skipped = csv_import_rows(args.csv, source=args.source, period_start=period_start, period_end=period_end)
        rows.extend(csv_rows)
        skipped.extend(csv_skipped)
    if args.total_pv is not None:
        metadata = {
            key: value
            for key, value in {
                "ipCount": args.ip_count,
                "bounceRate": args.bounce_rate,
                "averageVisitDuration": args.average_visit_duration,
            }.items()
            if value not in (None, "")
        }
        rows.append(
            total_import_row(
                source=args.source,
                period_start=period_start,
                period_end=period_end,
                total_pv=args.total_pv,
                visitor_count=args.visitor_count,
                metadata=metadata,
            )
        )

    if not rows:
        raise SystemExit("No import rows were produced.")
    if args.write:
        write_import_rows(rows)
    if args.baseline_config:
        update_baseline_config(rows)

    print(json.dumps(summarize(rows, skipped, write=args.write, baseline_config=args.baseline_config), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
