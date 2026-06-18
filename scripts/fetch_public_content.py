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

try:
    from scripts.runtime_paths import APP_ROOT, PUBLIC_FETCH_DIR, SITE_DATA_PATH, ensure_runtime_dirs
except ModuleNotFoundError:
    from runtime_paths import APP_ROOT, PUBLIC_FETCH_DIR, SITE_DATA_PATH, ensure_runtime_dirs

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from scripts import build_site_data

SOURCE_ROOTS = [APP_ROOT]
TIMEOUT = 15
USER_AGENT = "api-relay-rank/0.1 (+https://local.codex)"
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
LOCALHOST_PATTERN = re.compile(r"^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$", re.IGNORECASE)
BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._~+\-/=]+", re.IGNORECASE)
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
APP_CONFIG_PATTERN = re.compile(
    r"window\.__APP_CONFIG__\s*=\s*(\{.*?\})\s*;?\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
PAY_SHOP_PATTERN = re.compile(r"https?://pay\.ldxp\.cn/shop/([A-Za-z0-9_-]+)")
USD_AMOUNT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:刀|美元|USD|\$)", re.IGNORECASE)
ASSET_URL_PATTERN = re.compile(r"""(?:src|href)=["']([^"']+\.(?:js|mjs))["']""", re.IGNORECASE)
HOME_CHUNK_PATTERN = re.compile(r"""["']([^"']*HomeView-[^"']+\.js)["']""", re.IGNORECASE)
PUBLIC_PRICING_ASSET_MARKERS = (
    "ffm-plan-card",
    "充值倍率",
    "充值无门槛",
    "平台积分",
    "1 RMB = $1",
    "¥10",
    "MTok",
)


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


def prepend_station_url(stations: dict[str, dict[str, Any]], station_key: str, url: str) -> None:
    normalized_url = normalize_base_url(url)
    if not is_public_station_key(station_key) or not normalized_url or not is_public_base_url(normalized_url):
        return
    entry = stations.setdefault(station_key, {"station": station_key, "platform_guess": "", "urls": []})
    urls = entry.setdefault("urls", [])
    if not isinstance(urls, list):
        urls = []
        entry["urls"] = urls
    urls[:] = [item for item in urls if item != normalized_url]
    urls.insert(0, normalized_url)


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

    station_aliases = build_site_data.load_station_aliases()
    for station_key, override_url in build_site_data.load_station_url_overrides(station_aliases).items():
        prepend_station_url(station_map, station_key, override_url)

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
    path.write_text(redact_snapshot_content(content), encoding="utf-8")


def redact_snapshot_content(content: str) -> str:
    content = EMAIL_PATTERN.sub("xxx", content)
    content = BEARER_PATTERN.sub("Bearer <redacted>", content)
    content = JWT_PATTERN.sub("xxx", content)
    content = SK_PATTERN.sub("sk-<redacted>", content)
    return content


def sanitize_existing_public_fetch_snapshots() -> list[str]:
    if not PUBLIC_FETCH_DIR.exists():
        return []
    changed: list[str] = []
    for path in sorted(PUBLIC_FETCH_DIR.glob("*")):
        if path.suffix.lower() not in {".json", ".html"}:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except OSError:
            continue
        redacted = redact_snapshot_content(original)
        if redacted != original:
            path.write_text(redacted, encoding="utf-8")
            try:
                changed.append(path.relative_to(APP_ROOT).as_posix())
            except ValueError:
                changed.append(path.name)
    return changed


def status_candidates(base_url: str) -> list[str]:
    return [
        urljoin(base_url.rstrip("/") + "/", "api/status"),
        urljoin(base_url.rstrip("/") + "/", "api/v1/settings/public"),
    ]


def pricing_candidates(base_url: str) -> list[str]:
    return [
        urljoin(base_url.rstrip("/") + "/", "api/public/shop/products"),
        urljoin(base_url.rstrip("/") + "/", "api/pricing"),
        urljoin(base_url.rstrip("/") + "/", "api/subscription/plans"),
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
    subscription_plans_payload: dict[str, Any] | None = None,
    subscription_plans_source_url: str = "",
) -> dict[str, Any]:
    payload = dict(pricing_payload)
    if status_payload is not None:
        payload["status_payload"] = status_payload
    if subscription_plans_payload is not None:
        payload["subscription_plans_payload"] = subscription_plans_payload
        payload["subscription_plans_source_url"] = subscription_plans_source_url
    payload.setdefault("source_url", source_url)
    return payload


def fetch_subscription_plans_payload(client: requests.Session, base_url: str) -> tuple[dict[str, Any] | None, str]:
    source_url = urljoin(base_url.rstrip("/") + "/", "api/subscription/plans")
    try:
        payload = fetch_json(client, source_url)
    except Exception:
        return None, source_url
    return payload, source_url


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


def same_origin_asset_url(page_url: str, asset_ref: str) -> str:
    asset_url = urljoin(page_url, asset_ref)
    page_parts = urlparse(page_url)
    asset_parts = urlparse(asset_url)
    if page_parts.scheme != asset_parts.scheme or page_parts.netloc != asset_parts.netloc:
        return ""
    return asset_url


def html_asset_urls(page_url: str, html: str) -> list[str]:
    urls: list[str] = []
    for match in ASSET_URL_PATTERN.finditer(html):
        asset_url = same_origin_asset_url(page_url, match.group(1))
        if asset_url and asset_url not in urls:
            urls.append(asset_url)
    return urls


def home_chunk_urls(page_url: str, script_text: str) -> list[str]:
    urls: list[str] = []
    for match in HOME_CHUNK_PATTERN.finditer(script_text):
        asset_url = same_origin_asset_url(page_url, match.group(1))
        if asset_url and asset_url not in urls:
            urls.append(asset_url)
    return urls


def augment_html_with_linked_pricing_assets(client: requests.Session, page_url: str, html: str) -> str:
    appended: list[str] = []
    visited: set[str] = set()
    candidate_urls = html_asset_urls(page_url, html)
    for asset_url in candidate_urls[:4]:
        if asset_url in visited:
            continue
        visited.add(asset_url)
        try:
            asset_text, _content_type = fetch_text(client, asset_url)
        except Exception:
            continue
        if any(marker in asset_text for marker in PUBLIC_PRICING_ASSET_MARKERS):
            appended.append(f"\n<!-- public-fetch linked pricing asset: {asset_url} -->\n{asset_text}\n")
        for chunk_url in home_chunk_urls(asset_url, asset_text):
            if chunk_url in visited:
                continue
            visited.add(chunk_url)
            try:
                chunk_text, _chunk_type = fetch_text(client, chunk_url)
            except Exception:
                continue
            if any(marker in chunk_text for marker in PUBLIC_PRICING_ASSET_MARKERS):
                appended.append(f"\n<!-- public-fetch linked pricing asset: {chunk_url} -->\n{chunk_text}\n")
    if not appended:
        return html
    return html + "".join(appended)


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
        raw_payload: dict[str, Any] | None = None
        subscription_payload: dict[str, Any] | None = None
        subscription_source_url = ""
        if suffix == ".json":
            try:
                loaded_payload = json.loads(text)
            except json.JSONDecodeError:
                loaded_payload = None
            if isinstance(loaded_payload, dict):
                raw_payload = loaded_payload
                if candidate.rstrip("/").endswith("/api/pricing"):
                    subscription_payload, subscription_source_url = fetch_subscription_plans_payload(client, base_url)
                if not candidate.rstrip("/").endswith("/api/status"):
                    structured_probe_text = json.dumps(
                        combine_status_and_pricing_payload(
                            None,
                            raw_payload,
                            candidate,
                            subscription_payload,
                            subscription_source_url,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                    if not pricing_snapshot_has_structured_data(structured_probe_text, suffix):
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
                text = json.dumps(
                    combine_status_and_pricing_payload(
                        status_payload,
                        raw_payload,
                        candidate,
                        subscription_payload,
                        subscription_source_url,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
        else:
            text = augment_html_with_linked_pricing_assets(client, candidate, text)
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


def parse_station_filter(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def main() -> int:
    ensure_runtime_dirs()
    parser = argparse.ArgumentParser(description="抓取中转站公开公告与倍率快照。")
    parser.add_argument("--announcements", action="store_true", help="抓取公告快照。")
    parser.add_argument("--multiplier-snapshots", action="store_true", help="抓取公开倍率/价格快照。")
    parser.add_argument("--stations", default="", help="逗号分隔的站点 key；默认抓取全部候选站点。")
    parser.add_argument("--skip-build", action="store_true", help="抓取完成后不重建前端 JSON。")
    parser.add_argument("--quiet", action="store_true", help="仅输出最终 JSON 报告。")
    args = parser.parse_args()

    if not args.announcements and not args.multiplier_snapshots:
        args.announcements = True
        args.multiplier_snapshots = True

    client = session()
    report: list[dict[str, Any]] = []
    selected_stations = parse_station_filter(args.stations)

    for station in load_stations():
        station_key = station["station"]
        if selected_stations and station_key not in selected_stations:
            continue
        base_url = station["urls"][0]
        row_report: dict[str, Any] = {"station": station_key, "base_url": base_url}

        if args.announcements:
            row_report.update(refresh_status_snapshot(client, station_key, base_url))

        if args.multiplier_snapshots:
            if "status_snapshots" not in row_report:
                row_report.update(refresh_status_snapshot(client, station_key, base_url))

            row_report.update(refresh_pricing_snapshots(client, station_key, base_url))

        report.append(row_report)

    sanitized_existing = sanitize_existing_public_fetch_snapshots()

    if not args.skip_build:
        run_build_site_data()

    print(json.dumps({"updated": report, "sanitized_existing": sanitized_existing}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
