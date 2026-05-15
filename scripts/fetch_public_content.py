#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
PUBLIC_FETCH_DIR = WORKSPACE_ROOT / "_public_fetch"
TIMEOUT = 15
USER_AGENT = "api-relay-rank/0.1 (+https://local.codex)"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def split_urls(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def load_stations() -> list[dict[str, Any]]:
    rows = read_csv(WORKSPACE_ROOT / "login_verification_checklist.csv")
    stations: list[dict[str, Any]] = []
    for row in rows:
        urls = split_urls(row.get("urls"))
        if not urls:
            continue
        stations.append(
            {
                "station": row.get("station", ""),
                "platform_guess": row.get("platform_guess", ""),
                "urls": urls,
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
            row_report["announcements"] = []
            for candidate in status_candidates(base_url):
                try:
                    payload = fetch_json(client, candidate)
                except Exception as exc:  # noqa: BLE001
                    row_report["announcements"].append({"url": candidate, "ok": False, "error": repr(exc)})
                    continue
                if payload:
                    snapshot_path = PUBLIC_FETCH_DIR / f"{station_key}_status.json"
                    write_snapshot(snapshot_path, json.dumps(payload, ensure_ascii=False, indent=2))
                    row_report["announcements"].append({"url": candidate, "ok": True, "path": str(snapshot_path)})
                    break

        if args.multiplier_snapshots:
            row_report["multiplier_snapshots"] = []
            for candidate in pricing_candidates(base_url):
                try:
                    text, content_type = fetch_text(client, candidate)
                except Exception as exc:  # noqa: BLE001
                    row_report["multiplier_snapshots"].append({"url": candidate, "ok": False, "error": repr(exc)})
                    continue
                suffix = ".json" if "json" in content_type or text.lstrip().startswith("{") else ".html"
                snapshot_path = PUBLIC_FETCH_DIR / f"{station_key}_pricing{suffix}"
                write_snapshot(snapshot_path, text)
                row_report["multiplier_snapshots"].append({"url": candidate, "ok": True, "path": str(snapshot_path)})
                break

        report.append(row_report)

    if not args.skip_build:
        run_build_site_data()

    print(json.dumps({"updated": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
