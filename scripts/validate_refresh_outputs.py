#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_paths import LIVE_AUTH_PROBE_DIR, SITE_DATA_PATH
except ModuleNotFoundError:
    from runtime_paths import LIVE_AUTH_PROBE_DIR, SITE_DATA_PATH

REQUIRED_NEXUS_ENDPOINTS = (
    "/api/v1/groups/available",
    "/api/v1/payment/config",
    "/api/v1/payment/checkout-info",
    "/api/v1/payment/plans",
)
EVIDENCE_KEYS = {"groupMultipliers", "rechargeTiers", "announcements"}
ALLOWED_EVIDENCE_STATUSES = {"captured", "empty", "failed", "missing", "login_required", "blocked", "public_missing"}
SENSITIVE_SECRET_KEYS = {
    "token",
    "accesstoken",
    "refreshtoken",
    "authtoken",
    "sessiontoken",
    "authorization",
    "cookie",
    "setcookie",
    "password",
    "secret",
}


def read_json(path: Path) -> Any:
    last_error: Exception | None = None
    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate daily site-data refresh outputs.")
    parser.add_argument("--site-data", type=Path, default=SITE_DATA_PATH)
    parser.add_argument("--scrape-report", type=Path)
    parser.add_argument("--probe-dir", type=Path, default=LIVE_AUTH_PROBE_DIR)
    parser.add_argument("--skip-scrape-validation", action="store_true")
    return parser.parse_args()


def secret_values_from_env() -> list[str]:
    values = []
    for name in ("API_RELAY_SCRAPE_EMAIL", "API_RELAY_SCRAPE_PASSWORD"):
        value = os.environ.get(name, "").strip()
        if len(value) >= 6:
            values.append(value)
    return values


def assert_no_secret_leak(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for key, value in walk_items(payload):
        normalized_key = "".join(ch for ch in key.lower() if ch.isalnum())
        if normalized_key not in SENSITIVE_SECRET_KEYS:
            continue
        text_value = str(value or "")
        if text_value and not text_value.startswith("<redacted:"):
            raise SystemExit(f"Potential unredacted secret field in refresh output: {key}")
    for secret in secret_values_from_env():
        if secret and secret in text:
            raise SystemExit("Refresh output contains a configured secret value.")


def walk_items(value: Any) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if isinstance(child, (dict, list)):
                items.extend(walk_items(child))
            else:
                items.append((key_text, child))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                items.extend(walk_items(child))
    return items


def validate_scrape_report(path: Path) -> list[dict[str, Any]]:
    report = read_json(path)
    if not isinstance(report, list) or not report:
        raise SystemExit("Live auth scrape report is empty or not a list.")
    assert_no_secret_leak(report)
    attempted = [item for item in report if isinstance(item, dict) and item.get("station")]
    if not attempted:
        raise SystemExit("Live auth scrape report does not contain any attempted station.")
    if not any(item.get("station") == "nexus" for item in attempted):
        raise SystemExit("Live auth scrape report did not attempt nexus.")
    return attempted


def validate_nexus_probe(probe_dir: Path) -> None:
    path = probe_dir / "nexus-live-auth-probe.json"
    probe = read_json(path)
    if not isinstance(probe, dict):
        raise SystemExit("Nexus live auth probe is not a JSON object.")
    assert_no_secret_leak(probe)
    results = probe.get("results")
    if not isinstance(results, dict):
        raise SystemExit("Nexus live auth probe has no results object.")
    for endpoint in REQUIRED_NEXUS_ENDPOINTS:
        entry = results.get(endpoint)
        if not isinstance(entry, dict):
            raise SystemExit(f"Nexus live auth probe missing {endpoint}.")
        status = int(entry.get("status") or 0)
        if not (200 <= status < 300) or entry.get("ok") is not True:
            raise SystemExit(f"Nexus live auth probe endpoint is not 2xx: {endpoint} status={status}")


def find_station(site_data: dict[str, Any], key: str) -> dict[str, Any]:
    for station in site_data.get("stations", []):
        if isinstance(station, dict) and station.get("key") == key:
            return station
    raise SystemExit(f"Missing station in site-data: {key}")


def validate_site_data(path: Path) -> None:
    site_data = read_json(path)
    if not isinstance(site_data, dict):
        raise SystemExit("site-data is not a JSON object.")
    assert_no_secret_leak(site_data)
    nexus = find_station(site_data, "nexus")
    if not nexus.get("groupMultipliers"):
        raise SystemExit("Nexus groupMultipliers is empty after refresh.")
    if not nexus.get("rechargeTiers"):
        raise SystemExit("Nexus rechargeTiers is empty after refresh.")

    evidence = nexus.get("dataEvidence")
    if not isinstance(evidence, list):
        raise SystemExit("Nexus dataEvidence is missing.")
    by_key = {item.get("key"): item for item in evidence if isinstance(item, dict)}
    missing = sorted(EVIDENCE_KEYS - set(by_key))
    if missing:
        raise SystemExit(f"Nexus dataEvidence missing keys: {', '.join(missing)}")
    for key in EVIDENCE_KEYS:
        status = by_key[key].get("status")
        if status not in ALLOWED_EVIDENCE_STATUSES:
            raise SystemExit(f"Unexpected evidence status for {key}: {status}")

    for station in site_data.get("stations", []):
        if not isinstance(station, dict):
            continue
        for item in station.get("dataEvidence", []):
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            if status not in ALLOWED_EVIDENCE_STATUSES:
                raise SystemExit(f"Unexpected evidence status for {station.get('key')}:{item.get('key')} = {status}")


def main() -> int:
    args = parse_args()
    if args.skip_scrape_validation:
        if args.scrape_report:
            raise SystemExit("Do not combine --skip-scrape-validation with --scrape-report.")
    else:
        if not args.scrape_report:
            raise SystemExit("--scrape-report is required unless --skip-scrape-validation is set.")
        validate_scrape_report(args.scrape_report)
        validate_nexus_probe(args.probe_dir)
    validate_site_data(args.site_data)
    print(json.dumps({"validated": True, "skipScrapeValidation": bool(args.skip_scrape_validation)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
