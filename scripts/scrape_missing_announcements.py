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
    "muskai": "https://aiapi.muskpay.top",
    "printcap": "https://printcap.ai",
    "audit-api-printcap-ai": "https://printcap.ai",
}

TOKEN_KEYS = ("token", "password", "secret", "authorization", "cookie")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log in to stations and capture announcement API evidence.")
    parser.add_argument("--email", default=os.environ.get("API_RELAY_SCRAPE_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("API_RELAY_SCRAPE_PASSWORD", ""))
    parser.add_argument("--stations", default="", help="Comma-separated station keys; default = stations with empty announcements.")
    parser.add_argument("--skip", default="", help="Comma-separated station keys to skip.")
    parser.add_argument("--write-probes", action="store_true", help="Merge captured endpoint results into tabbit-audit-profile probes.")
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def station_rows(selected: set[str] | None, skipped: set[str]) -> list[dict[str, Any]]:
    site_data = read_json(SITE_DATA_PATH)
    rows: list[dict[str, Any]] = []
    for station in site_data.get("stations", []):
        key = str(station.get("key") or "")
        if not key or key in skipped:
            continue
        if selected is not None and key not in selected:
            continue
        if selected is None and station.get("announcements"):
            continue
        base = BASE_OVERRIDES.get(key) or normalize_base_url(station.get("url"))
        if not base:
            continue
        rows.append(
            {
                "key": key,
                "label": station.get("label") or key,
                "platform": str(station.get("platformGuess") or "").lower(),
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
    return True


def collection_from(value: Any, *, allow_text_item: bool = False) -> tuple[list[Any], bool]:
    if isinstance(value, list):
        return value, True
    if allow_text_item and isinstance(value, str) and looks_like_notice_text(value):
        return [{"content": value}], True
    if not isinstance(value, dict):
        return [], False
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


def login_sub2api(session: requests.Session, base_url: str, email: str, password: str) -> tuple[str, list[dict[str, Any]]]:
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


def login_new_api(session: requests.Session, base_url: str, email: str, password: str) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for payload in ({"username": email, "password": password}, {"email": email, "password": password}):
        result = hit(session, "POST", base_url.rstrip("/") + "/api/user/login", json=payload)
        body = result.get("body")
        attempts.append(
            {
                "path": "/api/user/login",
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


def login_special(session: requests.Session, base_url: str, email: str, password: str) -> tuple[str, list[dict[str, Any]]]:
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


def fetch_station(station: dict[str, Any], email: str, password: str) -> dict[str, Any]:
    base_url = station["base"].rstrip("/")
    session = client(base_url)
    platform = station["platform"]
    results: dict[str, dict[str, Any]] = {}
    login_attempts: list[dict[str, Any]] = []
    login_success = False

    public_paths = [
        "/api/status",
        "/api/notice",
        "/api/notices",
        "/api/v1/settings/public",
        "/api/settings/public",
        "/api/v1/announcements",
        "/api/announcements",
    ]
    for path in public_paths:
        results[path] = hit(session, "GET", base_url + path)

    if platform == "sub2api":
        token, login_attempts = login_sub2api(session, base_url, email, password)
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
        login_attempts = login_new_api(session, base_url, email, password)
        login_success = any(item.get("success") for item in login_attempts)
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
        token, login_attempts = login_special(session, base_url, email, password)
        login_success = bool(token) or any(item.get("success") for item in login_attempts)
        headers = {"Authorization": "Bearer " + token} if token else {}
        for path in ("/api/v1/announcements", "/api/announcements", "/api/status", "/api/notices", "/api/notice"):
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

    return {
        "station": station,
        "loginSuccess": login_success,
        "loginAttempts": login_attempts,
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

    payload.setdefault("location", base_url)
    payload.setdefault("url", base_url)
    payload.setdefault("title", station.get("label") or key)
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

    selected = {item.strip() for item in args.stations.split(",") if item.strip()} or None
    skipped = {item.strip() for item in args.skip.split(",") if item.strip()}
    captures = []
    for station in station_rows(selected, skipped):
        capture = fetch_station(station, args.email, args.password)
        capture["capturedAt"] = os.environ.get("API_RELAY_CAPTURED_AT", "")
        if args.write_probes:
            capture["probePath"] = str(merge_probe(capture))
        summary_attempts = capture["loginAttempts"][:3]
        captures.append(
            {
                "station": station["key"],
                "platform": station["platform"],
                "base": station["base"],
                "loginSuccess": capture["loginSuccess"],
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
