#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from scripts import build_site_data

SOURCE_ROOTS = [APP_ROOT]
SITE_DATA_PATH = APP_ROOT / "data" / "site-data.json"
PUBLIC_FETCH_DIR = Path(os.environ.get("PUBLIC_FETCH_DIR", APP_ROOT / "data" / "_public_fetch"))
TIMEOUT = 15
USER_AGENT = "api-relay-rank/0.1 (+https://local.codex)"
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
LOCALHOST_PATTERN = re.compile(r"^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$", re.IGNORECASE)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def resolve_source_path(filename: str) -> Path | None:
    for root in SOURCE_ROOTS:
        candidate = root / filename
        if candidate.exists():
            return candidate
    return None


def split_urls(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def is_public_station_key(station_key: Any) -> bool:
    text = str(station_key or "").strip()
    if not text:
        return False
    if EMAIL_PATTERN.search(text):
        return False
    if "printcap.ai-" in text.lower():
        return False
    if "://" in text:
        return False
    if any(ch in text for ch in "（）()"):
        return False
    return True


def is_public_base_url(value: Any) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.lower()
    return not LOCALHOST_PATTERN.fullmatch(host)


def normalize_base_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    parts = re.split(r"\s*(?:\||->)\s*", text)
    for candidate in parts:
        candidate = candidate.strip()
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        path = parsed.path or ""
        if path.endswith("/console") or path.endswith("/dashboard") or path.endswith("/wallet") or path.endswith("/keys"):
            path = path.rsplit("/", 1)[0]
        normalized = urlunparse((parsed.scheme, parsed.netloc, path or "", "", "", ""))
        return normalized.rstrip("/")
    return text


def load_stations() -> list[dict[str, Any]]:
    checklist_path = resolve_source_path("login_verification_checklist.csv")
    if checklist_path:
        rows = read_csv(checklist_path)
        stations: list[dict[str, Any]] = []
        for row in rows:
            station_key = row.get("station", "")
            if not is_public_station_key(station_key):
                continue
            urls = split_urls(row.get("urls"))
            if not urls:
                continue
            normalized_urls = [
                normalized
                for normalized in (normalize_base_url(url) for url in urls)
                if normalized and is_public_base_url(normalized)
            ]
            if not normalized_urls:
                continue
            stations.append(
                {
                    "station": station_key,
                    "platform_guess": row.get("platform_guess", ""),
                    "urls": normalized_urls,
                }
            )
        return stations

    if not SITE_DATA_PATH.exists():
        raise FileNotFoundError("Missing login_verification_checklist.csv and existing data/site-data.json")

    site_data = json.loads(SITE_DATA_PATH.read_text(encoding="utf-8"))
    stations = []
    for station in site_data.get("stations", []):
        station_key = station.get("key", "")
        if not is_public_station_key(station_key):
            continue
        url = str(station.get("url") or "").strip()
        normalized_url = normalize_base_url(url)
        if not normalized_url or not is_public_base_url(normalized_url):
            continue
        stations.append(
            {
                "station": station_key,
                "platform_guess": station.get("platformGuess", ""),
                "urls": [normalized_url],
            }
        )
    return stations


def session() -> requests.Session:
    client = requests.Session()
    client.headers.update({"User-Agent": USER_AGENT})
    return client


def fetch_json(client: requests.Session, url: str) -> dict[str, Any] | None:
    response = client.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    if "json" not in response.headers.get("content-type", "") and not response.text.lstrip().startswith("{"):
        return None
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def fetch_text(client: requests.Session, url: str) -> tuple[str, str]:
    response = client.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text, response.headers.get("content-type", "")


def write_snapshot(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def status_candidates(base_url: str) -> list[str]:
    return [urljoin(base_url.rstrip("/") + "/", "api/status")]


def pricing_candidates(base_url: str) -> list[str]:
    return [
        urljoin(base_url.rstrip("/") + "/", "api/pricing"),
        urljoin(base_url.rstrip("/") + "/", "pricing"),
    ]


def status_payload_announcements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    announcements = data.get("announcements")
    if not isinstance(announcements, list):
        return []
    return [item for item in announcements if isinstance(item, dict) and str(item.get("content") or "").strip()]


def parse_pricing_snapshot_content(content: str, suffix: str) -> dict[str, Any]:
    try:
        if suffix == ".json":
            payload = json.loads(content)
            if isinstance(payload, dict):
                return build_site_data.parse_public_pricing_payload(payload)
            return {"groupMultipliers": [], "rechargeTiers": [], "tierNotes": [], "sourceUrl": "", "stationTypeHint": ""}
        return build_site_data.parse_public_pricing_html(content)
    except json.JSONDecodeError:
        return {"groupMultipliers": [], "rechargeTiers": [], "tierNotes": [], "sourceUrl": "", "stationTypeHint": ""}


def pricing_snapshot_has_structured_data(content: str, suffix: str) -> bool:
    parsed = parse_pricing_snapshot_content(content, suffix)
    return bool(parsed.get("groupMultipliers") or parsed.get("rechargeTiers"))


def refresh_status_snapshot(client: requests.Session, station_key: str, base_url: str) -> dict[str, Any]:
    status_report: list[dict[str, Any]] = []
    for candidate in status_candidates(base_url):
        try:
            payload = fetch_json(client, candidate)
        except Exception as exc:  # noqa: BLE001
            status_report.append({"url": candidate, "ok": False, "error": repr(exc)})
            continue
        if payload is None:
            status_report.append(
                {
                    "url": candidate,
                    "ok": True,
                    "empty": True,
                    "skipped": True,
                    "preserved_existing": True,
                    "reason": "no_json_status_payload",
                }
            )
            continue
        announcement_count = len(status_payload_announcements(payload))
        if announcement_count == 0:
            status_report.append(
                {
                    "url": candidate,
                    "ok": True,
                    "empty": True,
                    "skipped": True,
                    "preserved_existing": True,
                    "reason": "no_standard_announcements",
                }
            )
            continue
        snapshot_path = PUBLIC_FETCH_DIR / f"{station_key}_status.json"
        write_snapshot(snapshot_path, json.dumps(payload, ensure_ascii=False, indent=2))
        status_report.append({"url": candidate, "ok": True, "path": str(snapshot_path), "announcement_count": announcement_count})
        break
    return {"status_snapshots": status_report}


def refresh_pricing_snapshots(client: requests.Session, station_key: str, base_url: str) -> dict[str, Any]:
    multiplier_report: list[dict[str, Any]] = []
    for candidate in pricing_candidates(base_url):
        try:
            text, content_type = fetch_text(client, candidate)
        except Exception as exc:  # noqa: BLE001
            multiplier_report.append({"url": candidate, "ok": False, "error": repr(exc)})
            continue

        suffix = ".json" if "json" in content_type or text.lstrip().startswith("{") else ".html"
        snapshot_path = PUBLIC_FETCH_DIR / f"{station_key}_pricing{suffix}"
        if not pricing_snapshot_has_structured_data(text, suffix):
            multiplier_report.append(
                {
                    "url": candidate,
                    "ok": True,
                    "empty": True,
                    "skipped": True,
                    "preserved_existing": True,
                }
            )
            continue

        write_snapshot(snapshot_path, text)
        multiplier_report.append(
            {
                "url": candidate,
                "ok": True,
                "path": str(snapshot_path),
                "empty": False,
            }
        )
        break
    return {"multiplier_snapshots": multiplier_report}


def run_build_site_data() -> None:
    subprocess.run(["python", "scripts/build_site_data.py"], cwd=APP_ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取中转站公开公告与倍率快照。")
    parser.add_argument("--announcements", action="store_true", help="抓取公告快照。")
    parser.add_argument("--multiplier-snapshots", action="store_true", help="抓取公开倍率/价格快照。")
    parser.add_argument("--skip-build", action="store_true", help="抓取完成后不重建前端 JSON。")
    parser.add_argument("--quiet", action="store_true", help="仅输出最终 JSON 报告。")
    args = parser.parse_args()

    if not args.announcements and not args.multiplier_snapshots:
        args.announcements = True
        args.multiplier_snapshots = True

    PUBLIC_FETCH_DIR.mkdir(parents=True, exist_ok=True)
    client = session()
    report: list[dict[str, Any]] = []

    for station in load_stations():
        station_key = station["station"]
        base_url = station["urls"][0]
        row_report: dict[str, Any] = {"station": station_key, "base_url": base_url}

        if args.announcements:
            row_report.update(refresh_status_snapshot(client, station_key, base_url))

        if args.multiplier_snapshots:
            if "status_snapshots" not in row_report:
                row_report.update(refresh_status_snapshot(client, station_key, base_url))

            row_report.update(refresh_pricing_snapshots(client, station_key, base_url))

        report.append(row_report)

    if not args.skip_build:
        run_build_site_data()

    print(json.dumps({"updated": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
