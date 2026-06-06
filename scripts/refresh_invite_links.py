#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    from scripts.runtime_paths import APP_ROOT, SITE_DATA_PATH, ensure_runtime_dirs
    from scripts.scrape_missing_announcements import (
        BASE_OVERRIDES,
        PLATFORM_OVERRIDES,
        blocked_login_attempt,
        client,
        hit,
        hit_raw,
        is_public_base_url,
        load_station_aliases,
        login_accounts_for_station,
        login_new_api,
        login_special,
        login_sub2api,
        normalize_base_url,
        read_json,
        redact_sensitive,
        station_env_key,
    )
except ModuleNotFoundError:
    from runtime_paths import APP_ROOT, SITE_DATA_PATH, ensure_runtime_dirs
    from scrape_missing_announcements import (
        BASE_OVERRIDES,
        PLATFORM_OVERRIDES,
        blocked_login_attempt,
        client,
        hit,
        hit_raw,
        is_public_base_url,
        load_station_aliases,
        login_accounts_for_station,
        login_new_api,
        login_special,
        login_sub2api,
        normalize_base_url,
        read_json,
        redact_sensitive,
        station_env_key,
    )

try:
    from scripts.build_site_data import canonical_station_key, is_public_station_key, is_public_station_url
except ModuleNotFoundError:
    from build_site_data import canonical_station_key, is_public_station_key, is_public_station_url


STATION_INVITE_LINKS_PATH = APP_ROOT / "config" / "station_invite_links.json"
DEFAULT_REPORT_PATH = APP_ROOT / ".local-artifacts" / "station-invite-link-capture-report.json"
INVITE_URL_KEYS = {
    "invite",
    "invite_link",
    "invite_url",
    "invitation",
    "invitation_link",
    "invitation_url",
    "referral",
    "referral_link",
    "referral_url",
    "affiliate",
    "affiliate_link",
    "affiliate_url",
    "promotion",
    "promotion_link",
    "promotion_url",
    "aff",
    "aff_link",
    "aff_url",
}
INVITE_PATHS = (
    "/affiliate",
    "/invite",
    "/invitation",
    "/promotion",
    "/referral",
    "/topup",
    "/console/topup",
    "/console/affiliate",
    "/console/invite",
    "/console/promotion",
    "/console/referral",
    "/console/user",
    "/console/profile",
    "/console/dashboard",
    "/dashboard/affiliate",
    "/dashboard/invite",
    "/dashboard/promotion",
    "/dashboard/referral",
    "/user/affiliate",
    "/user/invite",
    "/user/referral",
)
INVITE_API_PATHS = (
    "/api/user/invite",
    "/api/user/invites",
    "/api/user/affiliate",
    "/api/user/referral",
    "/api/user/promotion",
    "/api/user/self",
    "/api/user/profile",
    "/api/user/info",
    "/api/v1/user/invite",
    "/api/v1/user/invites",
    "/api/v1/user/affiliate",
    "/api/v1/user/referral",
    "/api/v1/user/promotion",
    "/api/v1/user/self",
    "/api/v1/user/profile",
    "/api/v1/user/info",
    "/api/v1/affiliate",
    "/api/v1/invite",
    "/api/v1/referral",
    "/api/v1/promotion",
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
INVITE_CODE_KEYS = {
    "aff",
    "aff_code",
    "affiliate_code",
    "affiliate_referral_code",
    "code",
    "invite_code",
    "invitation_code",
    "oauth_aff_code",
    "promotion_code",
    "ref",
    "ref_code",
    "referral_code",
}
INVITE_CODE_PATTERN = re.compile(
    r"(?:aff(?:iliate)?|invite|invitation|promo(?:tion)?|ref(?:erral)?)"
    r"(?:[_-]?(?:code|id))?['\"\s:=]+([A-Za-z0-9_-]{3,64})",
    re.IGNORECASE,
)
NON_INVITE_CODES = {"false", "null", "none", "true", "undefined"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture formal-ranking station invite links.")
    parser.add_argument("--stations", default="", help="Comma-separated station keys; default = formal ranking station union.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--write", action="store_true", help="Write discovered invite links into config/station_invite_links.json.")
    parser.add_argument("--force", action="store_true", help="Re-capture stations that already have configured invite links.")
    return parser.parse_args()


def read_invite_links() -> dict[str, str]:
    if not STATION_INVITE_LINKS_PATH.exists():
        return {}
    payload = read_json(STATION_INVITE_LINKS_PATH)
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if isinstance(value, str)}


def write_invite_links(links: dict[str, str]) -> None:
    STATION_INVITE_LINKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATION_INVITE_LINKS_PATH.write_text(json.dumps(dict(sorted(links.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def formal_ranking_station_keys(site_data: dict[str, Any], station_aliases: dict[str, str]) -> set[str]:
    keys: set[str] = set()
    rankings = site_data.get("rankings")
    if not isinstance(rankings, dict):
        return keys
    for rows in rankings.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = canonical_station_key(str(row.get("station") or ""), station_aliases)
            if key and is_public_station_key(key):
                keys.add(key)
    return keys


def ranked_station_rows(selected: set[str] | None, station_aliases: dict[str, str]) -> list[dict[str, str]]:
    site_data = read_json(SITE_DATA_PATH)
    if not isinstance(site_data, dict):
        raise SystemExit("site-data is not a JSON object.")
    ranked_keys = formal_ranking_station_keys(site_data, station_aliases)
    by_key = {
        canonical_station_key(str(station.get("key") or ""), station_aliases): station
        for station in site_data.get("stations", [])
        if isinstance(station, dict)
    }
    rows: list[dict[str, str]] = []
    for key in sorted(ranked_keys):
        if selected is not None and key not in selected:
            continue
        station = by_key.get(key, {})
        base = BASE_OVERRIDES.get(key) or normalize_base_url(station.get("url", ""))
        if not base or not is_public_base_url(base):
            continue
        rows.append(
            {
                "key": key,
                "label": str(station.get("label") or key),
                "base": base,
                "platform": str(PLATFORM_OVERRIDES.get(key) or station.get("platformGuess") or "").lower(),
            }
        )
    return rows


def station_invite_credentials(station_key: str) -> tuple[str, str]:
    env_key = station_env_key(station_key)
    if not env_key:
        return "", ""
    email = os.environ.get(f"API_RELAY_INVITE_{env_key}_EMAIL", "").strip()
    password = os.environ.get(f"API_RELAY_INVITE_{env_key}_PASSWORD", "").strip()
    return email, password


def login_station(station: dict[str, str], email: str, password: str) -> tuple[bool, list[dict[str, Any]], dict[str, str], Any]:
    session = client(station["base"])
    platform = station["platform"]
    attempts: list[dict[str, Any]] = []
    headers: dict[str, str] = {}
    login_success = False
    accounts = login_accounts_for_station(station["key"], email, password)

    if platform == "sub2api":
        token = ""
        for account in accounts:
            token, account_attempts = login_sub2api(session, station["base"], account["email"], account["password"], account_label=account["label"])
            attempts.extend(account_attempts)
            if token:
                break
        if token:
            login_success = True
            headers = {"Authorization": "Bearer " + token}
    elif platform == "new-api":
        for account in accounts:
            success, account_attempts = login_new_api(session, station["base"], account["email"], account["password"], account_label=account["label"])
            attempts.extend(account_attempts)
            if success:
                login_success = True
                break
        if login_success:
            self_result = hit(session, "GET", station["base"].rstrip("/") + "/api/user/self")
            body = self_result.get("body")
            data = body.get("data") if isinstance(body, dict) else None
            uid = ""
            if isinstance(data, dict):
                uid = str(data.get("id") or data.get("user_id") or data.get("uid") or "").strip()
            if uid:
                headers = {"New-Api-User": uid}
    else:
        token = ""
        for account in accounts:
            token, account_attempts = login_special(session, station["base"], account["email"], account["password"], account_label=account["label"])
            attempts.extend(account_attempts)
            if token or any(item.get("success") for item in account_attempts):
                login_success = True
                break
        if token:
            headers = {"Authorization": "Bearer " + token}
    return login_success, attempts, headers, session


def extract_urls(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).strip().lower()
            if lowered in INVITE_URL_KEYS and isinstance(child, str):
                found.extend(URL_PATTERN.findall(child))
            else:
                found.extend(extract_urls(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(extract_urls(child))
    elif isinstance(value, str):
        if any(marker in value.lower() for marker in ("invite", "aff", "referral", "promotion", "邀请", "推广", "返利")):
            found.extend(URL_PATTERN.findall(value))
    return list(dict.fromkeys(url.rstrip(".,);]") for url in found))


def extract_invite_codes(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).strip().lower()
            if lowered in INVITE_CODE_KEYS and isinstance(child, (str, int)):
                code = str(child).strip()
                if re.fullmatch(r"[A-Za-z0-9_-]{3,64}", code) and code.lower() not in NON_INVITE_CODES:
                    found.append(code)
            found.extend(extract_invite_codes(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(extract_invite_codes(child))
    elif isinstance(value, str):
        if any(marker in value.lower() for marker in ("invite", "aff", "referral", "promotion", "邀请", "推广", "返利")):
            found.extend(match.group(1) for match in INVITE_CODE_PATTERN.finditer(value) if match.group(1).lower() not in NON_INVITE_CODES)
    return list(dict.fromkeys(found))


def invite_urls_from_codes(codes: list[str], base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    candidates: list[str] = []
    for code in codes:
        candidates.extend(
            [
                f"{base}/register?aff={code}",
                f"{base}/register?invite={code}",
                f"{base}/register?ref={code}",
                f"{base}/signup?aff={code}",
                f"{base}/signup?invite={code}",
            ]
        )
    return candidates


def score_invite_url(url: str, base_url: str) -> tuple[int, int, str]:
    parsed = urlparse(url)
    base = urlparse(base_url)
    path_query = f"{parsed.path}?{parsed.query}".lower()
    score = 0
    if parsed.hostname and base.hostname and parsed.hostname.lower().removeprefix("www.") == base.hostname.lower().removeprefix("www."):
        score += 30
    if parsed.scheme == "https":
        score += 10
    for marker in ("invite", "invitation", "ref", "referral", "aff", "affiliate", "promotion", "promo"):
        if marker in path_query:
            score += 8
    if parsed.query:
        score += 4
    return score, -len(url), url


def best_invite_url(candidates: list[str], base_url: str) -> str:
    public_candidates = [url for url in candidates if is_public_station_url(url)]
    if not public_candidates:
        return ""
    return max(public_candidates, key=lambda url: score_invite_url(url, base_url))


def capture_invite_link(station: dict[str, str]) -> dict[str, Any]:
    email, password = station_invite_credentials(station["key"])
    if not email or not password:
        return {
            "station": station["key"],
            "base": station["base"],
            "status": "missing_credentials",
            "inviteUrl": "",
            "loginSuccess": False,
            "checkedPaths": [],
        }

    base_url = station["base"]
    login_success, attempts, headers, session = login_station(station, email, password)
    login_block = blocked_login_attempt(attempts)
    if not login_success:
        return {
            "station": station["key"],
            "base": station["base"],
            "status": "login_blocked" if login_block else "login_failed",
            "inviteUrl": "",
            "loginSuccess": False,
            "loginBlocked": bool(login_block),
            "blockPath": login_block.get("path", "") if login_block else "",
            "blockReason": login_block.get("reason", "") if login_block else "",
            "blockMessage": login_block.get("message", "") if login_block else "",
            "loginAttempts": redact_sensitive(attempts[:3]),
            "checkedPaths": [],
        }

    candidates: list[str] = []
    codes: list[str] = []
    checked_paths: list[str] = []

    for path in INVITE_API_PATHS:
        result = hit(session, "GET", base_url.rstrip("/") + path, headers=headers)
        checked_paths.append(path)
        body = result.get("body")
        if result.get("ok"):
            candidates.extend(extract_urls(body))
            codes.extend(extract_invite_codes(body))

    for path in INVITE_PATHS:
        result = hit_raw(session, "GET", urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), headers=headers)
        checked_paths.append(path)
        if result.get("ok"):
            body = redact_sensitive(result.get("body"))
            candidates.extend(extract_urls(body))
            codes.extend(extract_invite_codes(body))

    candidates.extend(invite_urls_from_codes(codes, base_url))
    invite_url = best_invite_url(candidates, base_url)
    return {
        "station": station["key"],
        "base": station["base"],
        "status": "captured" if invite_url else "not_found",
        "inviteUrl": invite_url,
        "loginSuccess": True,
        "checkedPaths": checked_paths,
    }


def main() -> int:
    args = parse_args()
    ensure_runtime_dirs()
    station_aliases = load_station_aliases()
    selected = {canonical_station_key(item.strip(), station_aliases) for item in args.stations.split(",") if item.strip()} or None
    existing_links = read_invite_links()
    captures: list[dict[str, Any]] = []
    links = dict(existing_links)
    skipped_configured: list[dict[str, str]] = []

    for station in ranked_station_rows(selected, station_aliases):
        existing_invite_url = existing_links.get(station["key"], "")
        if existing_invite_url and not args.force:
            skipped_configured.append(
                {
                    "station": station["key"],
                    "status": "skipped_configured",
                    "inviteUrl": existing_invite_url,
                }
            )
            continue
        capture = capture_invite_link(station)
        captures.append(capture)
        if args.write and capture.get("inviteUrl"):
            links[station["key"]] = str(capture["inviteUrl"])

    if args.write:
        write_invite_links(links)

    report = {
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "write": bool(args.write),
        "force": bool(args.force),
        "configuredInviteCount": len(links),
        "attempted": len(captures),
        "skippedConfiguredCount": len(skipped_configured),
        "skippedConfigured": skipped_configured,
        "captured": sum(1 for item in captures if item.get("status") == "captured"),
        "fallbackOfficialUrl": [
            {"station": item["station"], "status": item["status"]}
            for item in captures
            if item.get("status") != "captured" and item["station"] not in links
        ],
        "results": captures,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(redact_sensitive(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(redact_sensitive(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
