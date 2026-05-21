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
APP_CONFIG_PATTERN = re.compile(
    r"window\.__APP_CONFIG__\s*=\s*(\{.*?\})\s*;?\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
PAY_SHOP_PATTERN = re.compile(r"https?://pay\.ldxp\.cn/shop/([A-Za-z0-9_-]+)")
USD_AMOUNT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:刀|美元|USD|\$)", re.IGNORECASE)


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


def merge_station_map(stations: dict[str, dict[str, Any]], station_key: str, urls: list[str], platform_guess: str = "") -> None:
    if not is_public_station_key(station_key):
        return
    normalized_urls = [
        normalized
        for normalized in (normalize_base_url(url) for url in urls)
        if normalized and is_public_base_url(normalized)
    ]
    if not normalized_urls:
        return
    entry = stations.setdefault(station_key, {"station": station_key, "platform_guess": platform_guess, "urls": []})
    if platform_guess and not entry.get("platform_guess"):
        entry["platform_guess"] = platform_guess
    for url in normalized_urls:
        if url not in entry["urls"]:
            entry["urls"].append(url)


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
    station_map: dict[str, dict[str, Any]] = {}
    checklist_path = resolve_source_path("login_verification_checklist.csv")
    if checklist_path:
        rows = read_csv(checklist_path)
        for row in rows:
            station_key = row.get("station", "")
            merge_station_map(station_map, station_key, split_urls(row.get("urls")), row.get("platform_guess", ""))

    if not station_map and not SITE_DATA_PATH.exists():
        raise FileNotFoundError("Missing login_verification_checklist.csv and existing data/site-data.json")

    if SITE_DATA_PATH.exists():
        site_data = json.loads(SITE_DATA_PATH.read_text(encoding="utf-8"))
        for station in site_data.get("stations", []):
            station_key = station.get("key", "")
            merge_station_map(station_map, station_key, [str(station.get("url") or "").strip()], station.get("platformGuess", ""))

    candidate_path = resolve_source_path("request_log_station_candidates.csv")
    if candidate_path:
        for row in read_csv(candidate_path):
            host = row.get("host", "")
            urls = split_urls(row.get("url")) or ([f"https://{host}"] if host else [])
            merge_station_map(station_map, host, urls)

    return list(station_map.values())


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
    return [
        urljoin(base_url.rstrip("/") + "/", "api/status"),
        urljoin(base_url.rstrip("/") + "/", "api/v1/settings/public"),
    ]


def pricing_candidates(base_url: str) -> list[str]:
    return [
        urljoin(base_url.rstrip("/") + "/", "api/pricing"),
        urljoin(base_url.rstrip("/") + "/", "api/status"),
        base_url.rstrip("/") + "/",
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


def combine_status_and_pricing_payload(
    status_payload: dict[str, Any] | None,
    pricing_payload: dict[str, Any],
    source_url: str,
) -> dict[str, Any]:
    payload = dict(pricing_payload)
    if status_payload is not None:
        payload["status_payload"] = status_payload
    payload.setdefault("source_url", source_url)
    return payload


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
        is_sub2api_public_settings = candidate.rstrip("/").endswith("/api/v1/settings/public")
        announcement_count = len(status_payload_announcements(payload))
        if announcement_count == 0:
            if is_sub2api_public_settings:
                status_report.append(
                    {
                        "url": candidate,
                        "ok": True,
                        "empty": True,
                        "skipped": True,
                        "preserved_existing": True,
                        "reason": "settings_payload_without_announcements",
                    }
                )
                continue
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
    status_payload: dict[str, Any] | None = None
    try:
        status_payload = fetch_json(client, urljoin(base_url.rstrip("/") + "/", "api/status"))
    except Exception:
        status_payload = None
    for candidate in pricing_candidates(base_url):
        try:
            text, content_type = fetch_text(client, candidate)
        except Exception as exc:  # noqa: BLE001
            multiplier_report.append(
                {
                    "url": candidate,
                    "ok": False,
                    "error": repr(exc),
                    "skipped": True,
                    "preserved_existing": True,
                }
            )
            continue

        suffix = ".json" if "json" in content_type or text.lstrip().startswith("{") else ".html"
        if suffix == ".json":
            try:
                raw_payload = json.loads(text)
            except json.JSONDecodeError:
                raw_payload = None
            if isinstance(raw_payload, dict):
                text = json.dumps(
                    combine_status_and_pricing_payload(status_payload, raw_payload, candidate),
                    ensure_ascii=False,
                    indent=2,
                )
        else:
            app_config_match = APP_CONFIG_PATTERN.search(text)
            if app_config_match:
                try:
                    app_config = json.loads(app_config_match.group(1))
                except json.JSONDecodeError:
                    app_config = {}
                shop_urls: list[str] = []
                if isinstance(app_config, dict):
                    for value in (
                        app_config.get("balance_low_notify_recharge_url"),
                        app_config.get("purchase_subscription_url"),
                    ):
                        if isinstance(value, str):
                            shop_urls.append(value)
                    menu_items = app_config.get("custom_menu_items")
                    if isinstance(menu_items, list):
                        for item in menu_items:
                            if isinstance(item, dict) and isinstance(item.get("url"), str):
                                shop_urls.append(item["url"])
                for shop_url in shop_urls:
                    shop_match = PAY_SHOP_PATTERN.search(shop_url)
                    if not shop_match:
                        continue
                    snapshot = build_site_data.known_pay_shop_snapshot(shop_match.group(1), shop_url)
                    if snapshot and snapshot.get("rechargeTiers"):
                        suffix = ".json"
                        text = json.dumps(snapshot, ensure_ascii=False, indent=2)
                        break
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
                "skipped": False,
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
