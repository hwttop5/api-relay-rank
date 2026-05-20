#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
SITE_DATA_PATH = APP_ROOT / "data" / "site-data.json"
STATION_ALIASES_PATH = APP_ROOT / "config" / "station_aliases.json"
LIVE_AUTH_PROBE_DIR = WORKSPACE_ROOT / "tabbit-audit-profile"

TIMEOUT = 20
USER_AGENT = "api-relay-rank/0.1 live-announcement-capture"

BASE_OVERRIDES = {
    "aicodelink": "https://aicodelink.top",
    "coolplay": "https://cp.coolplay-api.fun:55555",
    "flymux": "https://api.flymux.com",
    "freemodel": "https://freemodel.dev",
    "gettoken": "https://gettoken.dev",
    "hongmacc": "https://hongmacc.com",
    "hi-code": "https://www.hi-code.cc",
    "muskai": "https://aiapi.muskpay.top",
    "printcap": "https://printcap.ai",
    "audit-api-printcap-ai": "https://printcap.ai",
}

PLATFORM_OVERRIDES = {
    "hi-code": "sub2api",
}

SPECIAL_ANNOUNCEMENT_PATHS = (
    "/api/v1/announcements",
    "/api/announcements",
    "/api/announcements/active?locale=zh-CN",
    "/api/announcements/active?locale=en",
    "/api/user/announcements",
    "/api/user/announcements/unread-popup",
    "/api/user/announcements/unread-count",
    "/api/status",
    "/api/notices",
    "/api/notice",
)

TOKEN_KEYS = ("token", "password", "secret", "authorization", "cookie")
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
LOCALHOST_PATTERN = re.compile(r"^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$", re.IGNORECASE)
BLOCK_MARKERS = ("turnstile", "captcha", "验证码", "人机验证", "风控")
ERROR_TEXT_MARKERS = (
    "404 page not found",
    "404 not found",
    "not found",
    "authorization header is required",
    "unauthorized",
    "invalid token",
    "forbidden",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log in to stations and capture announcement API evidence.")
    parser.add_argument("--email", default=os.environ.get("API_RELAY_SCRAPE_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("API_RELAY_SCRAPE_PASSWORD", ""))
    parser.add_argument("--stations", default="", help="Comma-separated station keys; default = stations with empty announcements.")
    parser.add_argument("--skip", default="", help="Comma-separated station keys to skip.")
    parser.add_argument("--all-stations", action="store_true", help="Capture every public station instead of only stations with missing announcements.")
    parser.add_argument("--write-probes", action="store_true", help="Merge captured endpoint results into tabbit-audit-profile probes.")
    return parser.parse_args()


def station_env_key(station_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(station_key or "").strip()).strip("_").upper()


def login_accounts_for_station(station_key: str, email: str, password: str) -> list[dict[str, str]]:
    accounts = [{"label": "primary", "email": email, "password": password}]
    env_key = station_env_key(station_key)
    if not env_key:
        return accounts

    fallback_email = os.environ.get(f"API_RELAY_SCRAPE_{env_key}_EMAIL", "").strip()
    fallback_password = os.environ.get(f"API_RELAY_SCRAPE_{env_key}_PASSWORD", "").strip() or password
    if fallback_email and fallback_password and (fallback_email != email or fallback_password != password):
        accounts.append({"label": f"{station_key}-fallback", "email": fallback_email, "password": fallback_password})
    return accounts


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_station_aliases() -> dict[str, str]:
    if not STATION_ALIASES_PATH.exists():
        return {}
    try:
        payload = read_json(STATION_ALIASES_PATH)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    aliases: dict[str, str] = {}
    for alias, canonical in payload.items():
        alias_key = str(alias or "").strip()
        canonical_key = str(canonical or "").strip()
        if alias_key and canonical_key and alias_key != canonical_key:
            aliases[alias_key] = canonical_key
    return aliases


def canonical_station_key(station_key: str, station_aliases: dict[str, str] | None = None) -> str:
    key = str(station_key or "").strip()
    aliases = station_aliases or {}
    seen: set[str] = set()
    while key in aliases and key not in seen:
        seen.add(key)
        next_key = str(aliases[key] or "").strip()
        if not next_key or next_key == key:
            break
        key = next_key
    return key


def normalize_base_url(value: Any) -> str:
    text = str(value or "").strip()
    parts = re.split(r"\s*(?:\||->)\s*", text)
    for candidate in parts:
        candidate = candidate.strip()
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        path = parsed.path or ""
        if path.endswith(("/console", "/dashboard", "/wallet", "/keys", "/purchase", "/pricing")):
            path = path.rsplit("/", 1)[0]
        return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", "")).rstrip("/")
    return ""


def is_public_station_key(station_key: Any) -> bool:
    text = str(station_key or "").strip()
    if not text:
        return False
    if EMAIL_PATTERN.search(text):
        return False
    lowered = text.lower()
    if "ttop5" in lowered:
        return False
    if "printcap.ai-" in lowered:
        return False
    if "://" in text:
        return False
    if any(ch in text for ch in "（）()"):
        return False
    return True


def is_public_base_url(value: Any) -> bool:
    parsed = urlparse(str(value or "").strip())
    host = parsed.netloc.lower()
    if not host:
        return False
    return not LOCALHOST_PATTERN.fullmatch(host)


def station_rows(
    selected: set[str] | None,
    skipped: set[str],
    station_aliases: dict[str, str] | None = None,
    *,
    include_all: bool = False,
) -> list[dict[str, Any]]:
    site_data = read_json(SITE_DATA_PATH)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for station in site_data.get("stations", []):
        key = canonical_station_key(str(station.get("key") or ""), station_aliases)
        if not key or key in skipped:
            continue
        if not is_public_station_key(key):
            continue
        if selected is not None and key not in selected:
            continue
        if selected is None and not include_all and station.get("announcements"):
            continue
        base = BASE_OVERRIDES.get(key) or normalize_base_url(station.get("url"))
        if not base or not is_public_base_url(base):
            continue
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "key": key,
                "label": station.get("label") or key,
                "platform": str(PLATFORM_OVERRIDES.get(key) or station.get("platformGuess") or "").lower(),
                "base": base,
            }
        )
    return rows


def client(base_url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": base_url,
            "Referer": base_url.rstrip("/") + "/",
        }
    )
    return session


def decode_body(response: requests.Response) -> Any:
    text = response.text
    try:
        return response.json()
    except ValueError:
        return text[:1200]


def hit(session: requests.Session, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = session.request(method, url, timeout=TIMEOUT, allow_redirects=False, **kwargs)
        return {
            "status": response.status_code,
            "ok": 200 <= response.status_code < 300,
            "body": redact_sensitive(decode_body(response)),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


def hit_raw(session: requests.Session, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = session.request(method, url, timeout=TIMEOUT, allow_redirects=False, **kwargs)
        return {
            "status": response.status_code,
            "ok": 200 <= response.status_code < 300,
            "body": decode_body(response),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in TOKEN_KEYS):
                redacted[key] = f"<redacted:{len(str(item or ''))}>"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    return value


def looks_like_notice_text(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    lowered = text[:300].lower()
    if lowered.startswith("<!doctype") or lowered.startswith("<html") or "<script" in lowered:
        return False
    if any(lowered.startswith(marker) for marker in ERROR_TEXT_MARKERS):
        return False
    if re.match(r"^\d{3}\s", lowered):
        return False
    return True


def collection_from(value: Any, *, allow_text_item: bool = False) -> tuple[list[Any], bool]:
    if isinstance(value, list):
        return value, True
    if allow_text_item and isinstance(value, str) and looks_like_notice_text(value):
        return [{"content": value}], True
    if not isinstance(value, dict):
        return [], False
    for key in ("announcement", "notice"):
        if key not in value:
            continue
        item = value.get(key)
        if item is None:
            return [], True
        if isinstance(item, list):
            return item, True
        if isinstance(item, dict):
            return [item], True
        if allow_text_item and isinstance(item, str) and looks_like_notice_text(item):
            return [{"content": item}], True
    for key in ("announcements", "items", "list", "records", "rows", "notices", "data"):
        if key not in value:
            continue
        rows, found = collection_from(value.get(key), allow_text_item=allow_text_item)
        if found:
            return rows, True
    return [], False


def announcement_count(entry: dict[str, Any] | None, *, allow_text_item: bool = False) -> int | None:
    if not isinstance(entry, dict):
        return None
    rows, found = collection_from(entry.get("body"), allow_text_item=allow_text_item)
    return len(rows) if found else None


def token_from(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    candidates: list[str] = []
    for container in (value, value.get("data") if isinstance(value.get("data"), dict) else None):
        if not isinstance(container, dict):
            continue
        for key in ("token", "access_token", "auth_token", "jwt", "session_token"):
            raw = container.get(key)
            if raw:
                candidates.append(str(raw))
    return max(candidates, key=len) if candidates else ""


def body_success(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return value.get("success") is True or value.get("code") == 0 or str(value.get("message") or "").lower() in {"success", "ok"}


def login_sub2api(
    session: requests.Session,
    base_url: str,
    email: str,
    password: str,
    *,
    account_label: str = "primary",
) -> tuple[str, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for payload in (
        {"email": email, "password": password},
        {"username": email, "password": password},
        {"account": email, "password": password},
    ):
        result = hit_raw(session, "POST", base_url.rstrip("/") + "/api/v1/auth/login", json=payload)
        body = result.get("body")
        token = token_from(body)
        safe_body = redact_sensitive(body)
        attempts.append(
            {
                "path": "/api/v1/auth/login",
                "account": account_label,
                "payloadKeys": list(payload.keys()),
                "status": result.get("status"),
                "ok": result.get("ok"),
                "message": safe_body.get("message") if isinstance(safe_body, dict) else str(safe_body)[:120],
                "reason": safe_body.get("reason") if isinstance(safe_body, dict) else "",
                "tokenLength": len(token),
            }
        )
        if token:
            return token, attempts
    return "", attempts


def login_new_api(
    session: requests.Session,
    base_url: str,
    email: str,
    password: str,
    *,
    account_label: str = "primary",
) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for payload in ({"username": email, "password": password}, {"email": email, "password": password}):
        result = hit(session, "POST", base_url.rstrip("/") + "/api/user/login", json=payload)
        body = result.get("body")
        attempts.append(
            {
                "path": "/api/user/login",
                "account": account_label,
                "payloadKeys": list(payload.keys()),
                "status": result.get("status"),
                "ok": result.get("ok"),
                "success": body_success(body),
                "message": body.get("message") if isinstance(body, dict) else str(body)[:120],
            }
        )
        if body_success(body):
            break
    return attempts


def login_special(
    session: requests.Session,
    base_url: str,
    email: str,
    password: str,
    *,
    account_label: str = "primary",
) -> tuple[str, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for path in ("/api/auth/login", "/api/login", "/api/user/login", "/api/v1/auth/login", "/api/account/login"):
        for payload in (
            {"email": email, "password": password},
            {"username": email, "password": password},
            {"account": email, "password": password},
        ):
            result = hit_raw(session, "POST", base_url.rstrip("/") + path, json=payload)
            body = result.get("body")
            token = token_from(body)
            success = body_success(body)
            safe_body = redact_sensitive(body)
            attempts.append(
                {
                    "path": path,
                    "account": account_label,
                    "payloadKeys": list(payload.keys()),
                    "status": result.get("status"),
                    "ok": result.get("ok"),
                    "success": success,
                    "message": safe_body.get("message") if isinstance(safe_body, dict) else str(safe_body)[:120],
                    "tokenLength": len(token),
                }
            )
            if token or success:
                return token, attempts
    return "", attempts


def blocked_login_attempt(login_attempts: list[dict[str, Any]]) -> dict[str, str] | None:
    for attempt in login_attempts:
        if not isinstance(attempt, dict):
            continue
        reason = str(attempt.get("reason") or "").strip()
        message = str(attempt.get("message") or "").strip()
        probe_text = json.dumps({"reason": reason, "message": message}, ensure_ascii=False).lower()
        if any(marker in probe_text for marker in BLOCK_MARKERS):
            return {
                "path": str(attempt.get("path") or "").strip(),
                "reason": reason,
                "message": message,
            }
    return None


def summarize_login_attempts(login_attempts: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    if len(login_attempts) <= limit:
        return login_attempts
    summary = login_attempts[: max(0, limit - 1)]
    for attempt in login_attempts[len(summary) :]:
        if attempt.get("success") or attempt.get("tokenLength") or attempt.get("ok") is True:
            summary.append(attempt)
            break
    if len(summary) < limit:
        summary.extend(login_attempts[len(summary) : limit])
    return summary[:limit]


def fetch_station(station: dict[str, Any], email: str, password: str) -> dict[str, Any]:
    base_url = station["base"].rstrip("/")
    session = client(base_url)
    platform = station["platform"]
    results: dict[str, dict[str, Any]] = {}
    login_attempts: list[dict[str, Any]] = []
    login_success = False
    accounts = login_accounts_for_station(station["key"], email, password)

    public_paths = [
        "/api/status",
        "/api/notice",
        "/api/notices",
        "/api/v1/settings/public",
        "/api/settings/public",
        "/api/v1/announcements",
        "/api/announcements",
        "/api/announcements/active?locale=zh-CN",
        "/api/announcements/active?locale=en",
    ]
    for path in public_paths:
        results[path] = hit(session, "GET", base_url + path)

    if platform == "sub2api":
        token = ""
        for account in accounts:
            token, attempts = login_sub2api(
                session,
                base_url,
                account["email"],
                account["password"],
                account_label=account["label"],
            )
            login_attempts.extend(attempts)
            if token:
                break
        if token:
            login_success = True
            headers = {"Authorization": "Bearer " + token}
            for path in (
                "/api/v1/auth/me",
                "/api/v1/groups/available",
                "/api/v1/payment/config",
                "/api/v1/payment/checkout-info",
                "/api/v1/payment/plans",
                "/api/v1/payment/subscriptions",
                "/api/v1/payment/orders",
                "/api/v1/announcements",
            ):
                results[path] = hit(session, "GET", base_url + path, headers=headers)
    elif platform == "new-api":
        for account in accounts:
            attempts = login_new_api(
                session,
                base_url,
                account["email"],
                account["password"],
                account_label=account["label"],
            )
            login_attempts.extend(attempts)
            if any(item.get("success") for item in attempts):
                login_success = True
                break
        for path in (
            "/api/status",
            "/api/notice",
            "/api/notices",
            "/api/announcement",
            "/api/announcements",
            "/api/user/announcement",
            "/api/user/announcements",
        ):
            results[path] = hit(session, "GET", base_url + path)
    else:
        token = ""
        for account in accounts:
            token, attempts = login_special(
                session,
                base_url,
                account["email"],
                account["password"],
                account_label=account["label"],
            )
            login_attempts.extend(attempts)
            if token or any(item.get("success") for item in attempts):
                login_success = True
                break
        headers = {"Authorization": "Bearer " + token} if token else {}
        for path in SPECIAL_ANNOUNCEMENT_PATHS:
            results[path] = hit(session, "GET", base_url + path, headers=headers)

    best_count = None
    best_path = ""
    for path, entry in results.items():
        if not any(marker in path.lower() for marker in ("announcement", "notice", "/api/status")):
            continue
        count = announcement_count(entry, allow_text_item="notice" in path.lower())
        if count is not None and (best_count is None or count > best_count):
            best_count = count
            best_path = path

    login_block = blocked_login_attempt(login_attempts)

    return {
        "station": station,
        "loginSuccess": login_success,
        "loginAttempts": login_attempts,
        "loginBlocked": bool(login_block),
        "blockReason": login_block.get("reason", "") if login_block else "",
        "blockMessage": login_block.get("message", "") if login_block else "",
        "blockPath": login_block.get("path", "") if login_block else "",
        "bestAnnouncementPath": best_path,
        "announcementCount": best_count,
        "results": results,
    }


def merge_probe(capture: dict[str, Any]) -> Path:
    station = capture["station"]
    key = station["key"]
    base_url = station["base"].rstrip("/")
    LIVE_AUTH_PROBE_DIR.mkdir(parents=True, exist_ok=True)
    path = LIVE_AUTH_PROBE_DIR / f"{key}-live-auth-probe.json"
    if path.exists():
        try:
            payload = read_json(path)
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    payload["location"] = base_url
    payload["url"] = base_url
    payload["title"] = station.get("label") or key
    if station.get("platform") == "sub2api":
        payload.setdefault("probe_type", "v1_generic")
        payload.setdefault("probe_kind", "v1_auth")
    results = payload.setdefault("results", {})
    if not isinstance(results, dict):
        results = {}
        payload["results"] = results
    for api_path, result in capture["results"].items():
        existing = results.get(api_path)
        # Keep old successful structured tier evidence unless this run has a useful response.
        if existing and api_path != "/api/v1/announcements" and result.get("ok") is not True:
            continue
        results[api_path] = result
    payload["announcementCapture"] = {
        "capturedAt": capture.get("capturedAt"),
        "loginSuccess": capture.get("loginSuccess"),
        "loginBlocked": capture.get("loginBlocked"),
        "blockReason": capture.get("blockReason"),
        "blockMessage": capture.get("blockMessage"),
        "blockPath": capture.get("blockPath"),
        "loginAttempts": capture.get("loginAttempts"),
        "bestAnnouncementPath": capture.get("bestAnnouncementPath"),
        "announcementCount": capture.get("announcementCount"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    if not args.email or not args.password:
        raise SystemExit("Missing --email/--password or API_RELAY_SCRAPE_EMAIL/API_RELAY_SCRAPE_PASSWORD.")

    station_aliases = load_station_aliases()
    selected = {item.strip() for item in args.stations.split(",") if item.strip()} or None
    skipped = {item.strip() for item in args.skip.split(",") if item.strip()}
    captures = []
    for station in station_rows(selected, skipped, station_aliases, include_all=args.all_stations):
        capture = fetch_station(station, args.email, args.password)
        capture["capturedAt"] = os.environ.get("API_RELAY_CAPTURED_AT", "")
        if args.write_probes:
            capture["probePath"] = str(merge_probe(capture))
        summary_attempts = summarize_login_attempts(capture["loginAttempts"])
        captures.append(
            {
                "station": station["key"],
                "platform": station["platform"],
                "base": station["base"],
                "loginSuccess": capture["loginSuccess"],
                "loginBlocked": capture.get("loginBlocked", False),
                "loginAttempts": summary_attempts,
                "bestAnnouncementPath": capture["bestAnnouncementPath"],
                "announcementCount": capture["announcementCount"],
                "probePath": capture.get("probePath", ""),
            }
        )

    print(json.dumps(captures, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
