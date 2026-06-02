#!/usr/bin/env python3
"""
Audit Codex Manager aggregate API proxy quality and fee multipliers.

The script separates verified cost evidence from site coverage hints:
- verified rankings only use tiers with a concrete group multiplier and recharge
  conversion basis;
- screenshot multipliers are ignored per the latest instruction;
- zero-multiplier verified groups must be excluded from ranking.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import sqlite3
import ssl
import statistics
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from scripts.station_display_names import normalize_station_label


WORKSPACE = Path(__file__).resolve().parent
RUNTIME_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", WORKSPACE / "data"))
DEFAULT_DB_PATH = Path(os.environ.get("APPDATA", "")) / "com.codexmanager.desktop" / "codexmanager.db"
DB_PATH = Path(os.environ.get("CODEX_MANAGER_DB_PATH", DEFAULT_DB_PATH))
GENERATED_AT = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
PROBE_TIMEOUT_SECONDS = 6
PLATFORM_PROBE_READ_BYTES = 1_000_000
VERIFIED_INPUT_PATH = WORKSPACE / "verified_multiplier_inputs.csv"
PUBLIC_FEE_EVIDENCE_PATH = WORKSPACE / "public_fee_evidence.csv"
STATION_PRICING_OVERRIDES_PATH = WORKSPACE / "config" / "station_pricing_overrides.json"
SITE_DATA_PATH = RUNTIME_DATA_DIR / "site-data.json"
REQUEST_LOG_STATION_CANDIDATES_PATH = WORKSPACE / "request_log_station_candidates.csv"
HIGH_MULTIPLIER_REVIEW_PATH = WORKSPACE / "high_multiplier_review.csv"
MULTIPLIER_SANITY_REVIEW_PATH = WORKSPACE / "multiplier_sanity_review.csv"
HIGH_MULTIPLIER_REVIEW_THRESHOLD = 2.0
LOW_MULTIPLIER_REVIEW_THRESHOLD = 0.001
LOG_REFRESH_STATE_PATH = RUNTIME_DATA_DIR / "codex-log-refresh-state.json"
LOG_REFRESH_STATE_VERSION = 1
LOG_REFRESH_OVERLAP_SECONDS = 300
PROCESSED_LOG_KEY_LIMIT = 50_000
LAST_LOG_REFRESH_INFO: dict[str, Any] = {}
PRIMARY_TIME_WINDOW = "work_hours"
TIME_WINDOW_LABELS = {
    "all_hours": "全部时段",
    "work_hours": "工作时段（工作日09:00:00-18:00:00）",
    "off_hours": "非工作时段（工作日18:00:01-次日08:59:59，周末全天）",
}
TIME_WINDOW_FILE_SUFFIX = {
    "all_hours": "all_hours",
    "work_hours": "workhours",
    "off_hours": "offhours",
}
WORK_HOUR_START = dt.time(9, 0, 0)
WORK_HOUR_END = dt.time(18, 0, 0)


@dataclass
class FeeTier:
    station: str
    label: str
    station_type: str
    group_name: str
    group_multiplier: float | None
    recharge_name: str
    billing_type: str
    rmb_amount: float | None
    usd_amount: float | None
    effective_multiplier: float | None
    recharge_location: str
    expires_rule: str
    verified: bool
    confidence: str
    source: str
    evidence_url: str
    participates_in_verified_ranking: bool
    notes: str = ""


@dataclass
class StationConfig:
    key: str
    label: str
    station_type: str = "unknown_pending"
    configured_urls: set[str] = field(default_factory=set)
    configured_suppliers: set[str] = field(default_factory=set)
    codex_status_hints: list[str] = field(default_factory=list)
    platform_guess: str = "unknown"


LABELS: dict[str, str] = {
    "17nas": "17Nas",
    "585016d3.u3u.dev": "U3U",
    "4router": "4Router",
    "aicodelink": "AICodeLink",
    "api.xiaoxin.best": "Xiaoxin",
    "atomflow.vip": "AtomFlow",
    "avemujica": "AveMujica",
    "audit-api-printcap-ai": "PrintcapAI",
    "bossclaw": "BossClaw",
    "bytecat": "ByteCat",
    "claude-api": "ClaudeAPI",
    "cnrouter": "CNRouter",
    "coai-work": "CoAIWork",
    "coolplay": "Coolplay",
    "dogcoding": "DogCoding",
    "euzhi": "Euzhi",
    "fishxcode.com": "FishXCode",
    "flymux": "FlyMux",
    "freemodel": "FreeModel",
    "guodongapi": "GuodongAPI",
    "hello-code": "HelloCode",
    "gettoken": "GetToken",
    "giot": "GIOT",
    "goapis": "GoAPIs",
    "happycode.vip": "Happycode",
    "52mx": "52Mx",
    "hi-code": "HiCode",
    "hongmacc": "HongMaCC",
    "hyperapi": "HyperAPI",
    "icodex.pro": "ICodex",
    "loomex": "Loomex",
    "lumibest": "LumiBest",
    "moosecloud.cc": "MooseCloud",
    "muskai": "MuskAI",
    "newcli": "NewCLI",
    "nbtoken.ai567.asia": "NBToken",
    "nexus": "Nexus",
    "opentk": "OpenTK",
    "onexmodel": "OneXModel",
    "prod.bbroot.com": "ProdBbroot",
    "qiuqiutoken": "QiuqiuToken",
    "shunfen6": "Shunfen6",
    "vbcode": "VBCode",
    "voapi": "VoAPI",
    "zerofra": "ZeroFra",
    "zhima": "Zhima",
}


def station_display_label(station_key: Any, raw_label: Any = "", station_url: Any = "") -> str:
    key = str(station_key or "").strip()
    return normalize_station_label(key, raw_label or LABELS.get(key, ""), station_url)


SCREENSHOT_ONLY_URLS: dict[str, str] = {
    "52mx": "https://52mx.net",
    "coai-work": "https://coaiwork.com",
    "hello-code": "http://hello-code.cn",
    "loomex": "https://www.loomex.top",
    "onexmodel": "https://1xm.ai",
    "vbcode": "https://vbcode.io",
}


SITE_URL_OVERRIDES: dict[str, str] = {
    "585016d3.u3u.dev": "https://585016d3.u3u.dev",
    "52mx": "https://52mx.net",
    "aicodelink": "https://aicodelink.top",
    "api-slb.krill-ai.com": "https://www.krill-ai.com",
    "api.xiaoxin.best": "https://api.xiaoxin.best",
    "atomflow.vip": "https://atomflow.vip",
    "audit-api-printcap-ai": "https://printcap.ai",
    "claude-api": "https://claude-api.org",
    "coai-work": "https://coaiwork.com",
    "coolplay": "https://cp.coolplay-api.fun:55555",
    "euzhi": "https://admin.euzhi.com",
    "fishxcode.com": "https://fishxcode.com",
    "freemodel": "https://freemodel.dev",
    "guodongapi": "https://guodongapi.site",
    "gettoken": "https://gettoken.dev",
    "happycode.vip": "https://happycode.vip",
    "hello-code": "http://hello-code.cn",
    "hi-code": "https://www.hi-code.cc",
    "icodex.pro": "https://icodex.pro",
    "loomex": "https://www.loomex.top",
    "moosecloud.cc": "https://moosecloud.cc",
    "muskai": "https://aiapi.muskpay.top",
    "onexmodel": "https://1xm.ai",
    "opentk": "https://opentk.ai",
    "prod.bbroot.com": "https://prod.bbroot.com",
    "qiuqiutoken": "https://api.qiuqiutoken.com",
    "vbcode": "https://vbcode.io",
    "voapi": "https://demo.voapi.top",
}


VERIFIED_INPUT_FIELDNAMES = [
    "station",
    "label",
    "station_type",
    "group_name",
    "group_multiplier",
    "recharge_name",
    "billing_type",
    "rmb_amount",
    "usd_amount",
    "effective_multiplier",
    "recharge_location",
    "expires_rule",
    "confidence",
    "source",
    "evidence_url",
    "participates_in_verified_ranking",
    "notes",
]


STATION_TYPE_LABELS = {
    "subscription": "subscription",
    "non_subscription": "non_subscription",
    "mixed": "mixed",
    "unknown_pending": "unknown_pending",
}


STATION_TYPE_LABELS_CN = {
    "subscription": "包月中转站",
    "non_subscription": "非包月中转站",
    "mixed": "混合型中转站",
    "unknown_pending": "待补证据",
}


BILLING_TYPE_LABELS_CN = {
    "monthly": "月卡",
    "weekly": "周卡",
    "daily": "日卡",
    "yearly": "年卡",
    "permanent": "永久额度",
    "permanent_or_unknown": "按量/有效期待核",
    "unknown": "未知",
}


CONFIDENCE_LABELS_CN = {
    "high_user_provided": "高置信-用户提供",
    "high_tabbit_logged_in": "高置信-Tabbit 登录页核验",
    "manual_verified": "高置信-人工录入核验",
    "public_structured_evidence": "公开结构化证据",
    "public_external_shop_verified": "公开外部店铺结构化证据",
    "low_public_notice": "低置信-公开公告",
    "low_public_notice_inferred_recharge": "低置信-公开信息推断充值倍率",
}


STATION_TYPE_OVERRIDES = {
    "585016d3.u3u.dev": "mixed",
    "4router": "non_subscription",
    "17nas": "mixed",
    "api.baobu.xyz": "non_subscription",
    "api-slb.krill-ai.com": "mixed",
    "api.xiaoxin.best": "mixed",
    "atomflow.vip": "non_subscription",
    "audit-api-printcap-ai": "non_subscription",
    "bytecat": "non_subscription",
    "bossclaw": "non_subscription",
    "claude360.xyz": "non_subscription",
    "cngpt.net": "non_subscription",
    "coolplay": "mixed",
    "dogcoding": "non_subscription",
    "euzhi": "non_subscription",
    "fishxcode.com": "non_subscription",
    "flymux": "non_subscription",
    "freemodel": "mixed",
    "giot": "non_subscription",
    "guodongapi": "mixed",
    "hi-code": "non_subscription",
    "hongmacc": "non_subscription",
    "hyperapi": "mixed",
    "icodex.pro": "unknown_pending",
    "lumibest": "non_subscription",
    "moosecloud.cc": "subscription",
    "muskai": "mixed",
    "newcli": "non_subscription",
    "nbtoken.ai567.asia": "mixed",
    "nexus": "non_subscription",
    "shunfen6": "mixed",
    "voapi": "non_subscription",
    "zhishu.dev": "mixed",
    "zhima": "non_subscription",
    "onexmodel": "mixed",
    "happycode.vip": "non_subscription",
    "prod.bbroot.com": "non_subscription",
}


PACKAGE_BILLING_TYPES = {"monthly", "weekly", "daily", "quarterly", "yearly"}
KRILL_ROUTE_MULTIPLIER = 0.2


LIVE_AUTH_PROBE_DIR = Path(os.environ.get("LIVE_AUTH_PROBE_DIR", WORKSPACE.parent / "tabbit-audit-profile"))
PENDING_API_PROBE_PATH = LIVE_AUTH_PROBE_DIR / "pending-stations-api-probes.json"
PENDING_API_PROBE_CACHE: dict[str, Any] | None = None


def workspace_public_path(path: Path) -> str:
    try:
        return path.relative_to(WORKSPACE).as_posix()
    except ValueError:
        return path.name


LIVE_AUTH_PROBE_CONFIG: dict[str, dict[str, Any]] = {
    "585016d3.u3u.dev": {
        "probe_type": "v1_generic",
        "station_type": "mixed",
    },
    "4router": {},
    "52mx": {},
    "aicodelink": {},
    "avemujica": {},
    "newcli": {
        "station_type": "non_subscription",
        "sampled_amounts": [10, 20, 50, 100, 200, 500],
    },
    "nbtoken.ai567.asia": {
        "station_type": "mixed",
    },
    "nexus": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
        "quick_amounts": [1, 10, 20, 50, 100, 200, 500],
    },
    "api.xiaoxin.best": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
    },
    "atomflow.vip": {
        "station_type": "non_subscription",
    },
    "audit-api-printcap-ai": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
        "quick_amounts": [1, 10, 20, 50, 100, 200, 500],
    },
    "bytecat": {
        "station_type": "non_subscription",
    },
    "bossclaw": {
        "probe_type": "v1_generic",
    },
    "claude-api": {
        "probe_type": "v1_generic",
    },
    "cnrouter": {},
    "coai-work": {},
    "api.baobu.xyz": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
        "quick_amounts": [1, 10, 20, 50, 100, 200, 500, 1000, 2000, 4000],
    },
    "api.feifeimiao.top": {
        "probe_type": "v1_generic",
        "station_type": "mixed",
        "quick_amounts": [10, 20, 50, 100, 200, 500, 1000, 2000, 4000],
    },
    "api.nerverun.com": {
        "probe_type": "v1_generic",
        "station_type": "mixed",
        "quick_amounts": [10, 20, 50, 100, 200, 500, 1000, 2000, 5000],
    },
    "api-slb.krill-ai.com": {
        "probe_type": "krill_special",
        "station_type": "mixed",
    },
    "dogcoding": {
        "probe_type": "v1_generic",
    },
    "euzhi": {},
    "guodongapi": {
        "probe_type": "v1_generic",
        "station_type": "mixed",
        "quick_amounts": [1, 5, 10, 20, 50, 100, 200, 500],
    },
    "hyperapi": {
        "station_type": "mixed",
    },
    "17nas": {
        "station_type": "mixed",
    },
    "flymux": {
        "station_type": "non_subscription",
        "probe_type": "flymux_special",
        "quick_amounts": [10, 20, 50, 100, 200, 500, 1000, 2000, 5000],
    },
    "giot": {},
    "goapis": {},
    "hello-code": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
        "quick_amounts": [10, 20, 50, 100, 200, 500, 1000, 2000, 5000],
        "allow_public_payment_disabled_wallet": True,
    },
    "hi-code": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
    },
    "loomex": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
        "quick_amounts": [1, 10, 20, 50, 100],
    },
    "lumibest": {},
    "onexmodel": {},
    "opentk": {
        "probe_type": "v1_generic",
    },
    "qiuqiutoken": {},
    "relayai.asia": {
        "probe_type": "v1_generic",
        "station_type": "non_subscription",
        "quick_amounts": [10, 20, 50, 100, 200, 500, 1000, 2000, 4000],
    },
    "shunfen6": {},
    "vbcode": {},
    "zerofra": {},
    "zhishu.dev": {
        "probe_type": "v1_generic",
        "station_type": "mixed",
    },
    "zhima": {
        "probe_type": "v1_generic",
    },
}


DETAIL_EVIDENCE_FEE_STATIONS = {
    "audit-api-printcap-ai",
    "api.code-relay.com",
    "api-slb.krill-ai.com",
    "claude360.xyz",
    "cngpt.net",
    "fishxcode.com",
    "fushengyunsuan.cn",
    "happycode.vip",
    "moosecloud.cc",
    "muskai",
    "prod.bbroot.com",
}


DETAIL_EVIDENCE_FEE_META: dict[str, dict[str, Any]] = {
    "audit-api-printcap-ai": {
        "confidence": "manual_verified",
        "source": "screenshot_verified_detail_baseline",
        "notes": "PrintCap detail rows come from manually verified recharge screenshot plus archived group evidence.",
    },
    "fishxcode.com": {
        "confidence": "public_structured_evidence",
        "source": "detail_page_public_structured_evidence",
        "notes": "FishXCode detail rows come from archived structured public status/pricing evidence.",
    },
    "fushengyunsuan.cn": {
        "confidence": "public_structured_evidence",
        "source": "detail_page_public_status_and_pricing_evidence",
        "notes": "Fushengyunsuan detail rows come from official public status quota conversion plus public pricing group evidence.",
    },
    "happycode.vip": {
        "confidence": "manual_verified",
        "source": "browser_screenshot_verified_external_shop",
        "notes": "Happycode detail rows come from browser verified external shop cards and manual group check.",
    },
    "prod.bbroot.com": {
        "confidence": "manual_verified",
        "source": "browser_screenshot_verified_usdc_checkout",
        "notes": "ProdBbroot detail rows come from browser verified group colors and USDC checkout page.",
    },
    "api.code-relay.com": {
        "confidence": "public_structured_evidence",
        "source": "detail_page_public_status_and_pricing_evidence",
        "notes": "Code Relay detail rows come from official public status quota conversion plus public pricing group evidence.",
    },
    "claude360.xyz": {
        "confidence": "public_structured_evidence",
        "source": "detail_page_public_status_and_pricing_evidence",
        "notes": "Claude360 detail rows come from public /api/status quota conversion plus public /api/pricing group evidence.",
    },
    "cngpt.net": {
        "confidence": "public_structured_evidence",
        "source": "detail_page_public_status_and_pricing_evidence",
        "notes": "CNGPT detail rows come from public /api/status quota conversion plus public /api/pricing group evidence.",
    },
    "api-slb.krill-ai.com": {
        "confidence": "high_tabbit_logged_in",
        "source": "krill_logged_in_shop_and_route_api",
        "notes": "Krill detail rows come from logged-in route settings plus official shop product APIs; homepage is https://www.krill-ai.com and api-slb.krill-ai.com is a route endpoint.",
    },
    "moosecloud.cc": {
        "confidence": "high_tabbit_logged_in",
        "source": "detail_page_live_probe_baseline",
        "notes": "MooseCloud detail rows come from archived logged-in API group and payment plan evidence.",
    },
    "muskai": {
        "confidence": "high_tabbit_logged_in",
        "source": "detail_page_live_probe_subscription_evidence",
        "notes": "MuskAI detail rows come from logged-in subscription plan evidence; plans are bound to the Codex subscription group and must not be cross-joined with wallet groups.",
        "groupRows": [{"groupName": "Codex订阅", "groupMultiplier": 1}],
    },
}


PENDING_API_PROBE_OVERRIDE_STATIONS = {
    "52mx",
    "aicodelink",
    "claude-api",
    "coai-work",
    "euzhi",
    "muskai",
    "onexmodel",
    "opentk",
    "qiuqiutoken",
    "vbcode",
}


class TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            text = " ".join(data.split())
            if text:
                self.title_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()


SUB2API_APP_CONFIG_KEYS = (
    "purchase_subscription_enabled",
    "table_default_page_size",
    "custom_menu_items",
    "custom_endpoints",
    "channel_monitor_enabled",
    "available_channels_enabled",
    "balance_low_notify_recharge_url",
)


def classify_platform_html(body: str, title: str) -> str:
    lowered = body.lower()
    title_lower = title.lower()
    if 'name="generator" content="new-api"' in lowered or "new api" in title_lower:
        return "new-api"

    has_sub2api_literal = "sub2api" in lowered or "subscription to api" in lowered
    has_sub2api_app_config = (
        "ai api gateway" in title_lower
        and "window.__app_config__" in lowered
        and sum(1 for key in SUB2API_APP_CONFIG_KEYS if key in lowered) >= 3
    )
    if has_sub2api_literal or has_sub2api_app_config:
        return "sub2api"

    if "ai api gateway" in title_lower:
        return "new-api-like"
    if "new-api" in lowered or "/console/token" in lowered or "/token" in lowered:
        return "new-api-like"
    return "special"


def fetch_platform_probe(url: str) -> tuple[str, str, str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 CodexMultiplierAudit/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_SECONDS, context=ctx) as resp:
        body = resp.read(PLATFORM_PROBE_READ_BYTES).decode("utf-8", errors="ignore")
        final_url = resp.geturl()
        status = str(getattr(resp, "status", ""))
    return body, final_url, status


def root_url(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    if not parsed.netloc:
        return url.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"


def public_host_from_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    try:
        parsed = urllib.parse.urlparse(raw_url.strip() if "://" in raw_url else "https://" + raw_url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None
    if host in {"localhost", "::1"} or host.startswith("127.") or host.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return None
    if "@" in host or "ttop5" in host:
        return None
    if "." not in host and address is None:
        return None
    return host


def station_key_from_public_url(raw_url: str | None) -> str | None:
    host = public_host_from_url(raw_url)
    return host if host and is_public_station_key(host) else None


def supplier_is_private(value: str | None) -> bool:
    lowered = str(value or "").strip().lower()
    return bool(lowered and ("@" in lowered or "ttop5" in lowered))


def redact_supplier_name(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if supplier_is_private(text):
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        return f"redacted-supplier-{digest}"
    return text


def is_private_account_station_key(key: str) -> bool:
    normalized = key.strip().lower()
    if not normalized:
        return True
    return "@" in normalized or "ttop5" in normalized


def is_public_station_key(key: str) -> bool:
    normalized = key.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if "@" in lowered or "ttop5" in lowered:
        return False
    if "://" in normalized:
        return False
    if any(ch in normalized for ch in "（）()"):
        return False
    return True


def is_local_station_url(raw_url: str | None) -> bool:
    if not raw_url:
        return False
    try:
        parsed = urllib.parse.urlparse(raw_url if "://" in raw_url else "https://" + raw_url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "::1"} or host.startswith("127.") or host.endswith(".local")


def station_urls_to_probe(station: StationConfig) -> list[str]:
    preferred = SITE_URL_OVERRIDES.get(station.key)
    urls = sorted(url for url in station.configured_urls if url != preferred)
    if preferred:
        urls = [preferred] + urls
    if urls:
        return urls
    return []


def classify_station(supplier: str | None, url: str | None) -> str | None:
    text = f"{supplier or ''} {url or ''}".lower()
    checks = [
        ("nexus", ["nexus", "1982video"]),
        ("585016d3.u3u.dev", ["585016d3.u3u.dev"]),
        ("atomflow.vip", ["atomflow.vip"]),
        ("hello-code", ["hello-code", "hello-code.cn"]),
        ("fishxcode.com", ["fishxcode", "fishxcode.com"]),
        ("moosecloud.cc", ["moosecloud", "moosecloud.cc"]),
        ("icodex.pro", ["icodex", "icodex.pro"]),
        ("freemodel", ["freemodel"]),
        ("voapi", ["voapi"]),
        ("newcli", ["newcli"]),
        ("nbtoken.ai567.asia", ["nbtoken.ai567.asia", "ai567"]),
        ("goapis", ["goapis"]),
        ("guodongapi", ["guodongapi"]),
        ("dogcoding", ["laodog", "dogcoding"]),
        ("giot", ["giot"]),
        ("coolplay", ["coolplay"]),
        ("loomex", ["loomex"]),
        ("lumibest", ["lumibest"]),
        ("hi-code", ["hi-code"]),
        ("shunfen6", ["shunfen6"]),
        ("qiuqiutoken", ["qiuqiutoken"]),
        ("vbcode", ["vbcode"]),
        ("flymux", ["flymux", "106.75.146.14"]),
        ("euzhi", ["euzhi"]),
        ("bossclaw", ["bossclaw"]),
        ("muskai", ["muskpay", "muskai"]),
        ("gettoken", ["gettoken"]),
        ("hongmacc", ["hongmacc"]),
        ("hyperapi", ["hyperapi"]),
        ("zerofra", ["zerofra"]),
        ("bytecat", ["bytecat"]),
        ("17nas", ["17nas"]),
        ("52mx", ["52mx", "52mx.net"]),
        ("api.baobu.xyz", ["baobu", "api.baobu.xyz"]),
        ("claude360.xyz", ["claude360.xyz", "claude360"]),
        ("cngpt.net", ["cngpt.net", "cngpt"]),
        ("claude-api", ["claude-api"]),
        ("coai-work", ["coai"]),
        ("api-slb.krill-ai.com", ["krill-ai", "krill.ai", "api-slb.krill-ai.com", "www.krill-ai.com"]),
        ("audit-api-printcap-ai", ["api.printcap.ai", "printcap"]),
        ("onexmodel", ["onexmodel", "onex", "1xm.ai", "1xm"]),
        ("4router", ["4router"]),
        ("zhima", ["zhima"]),
        ("aicodelink", ["aicodelink"]),
        ("api.xiaoxin.best", ["xiaoxin"]),
        ("avemujica", ["avemujica"]),
        ("opentk", ["opentk"]),
        ("cnrouter", ["chrouter", "cnrouter"]),
    ]
    for key, needles in checks:
        if any(needle in text for needle in needles):
            return key
    return None


def db_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Codex Manager DB not found: {DB_PATH}")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def postgres_connection() -> Any:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required when --log-source postgres is used.")
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(database_url, row_factory=dict_row)


def load_station_configs(*, log_source: str = "sqlite") -> dict[str, StationConfig]:
    stations: dict[str, StationConfig] = {
        key: StationConfig(key=key, label=station_display_label(key, label)) for key, label in LABELS.items()
    }
    if log_source == "sqlite":
        con = db_connection()
        try:
            query = """
                select supplier_name, url, status, last_test_status
                from aggregate_apis
                where url is not null
            """
            for row in con.execute(query):
                key = classify_station(row["supplier_name"], row["url"])
                if key is None:
                    key = station_key_from_public_url(row["url"])
                    if key is None:
                        continue
                station = stations.setdefault(
                    key,
                    StationConfig(key=key, label=station_display_label(key)),
                )
                station.configured_suppliers.add(redact_supplier_name(row["supplier_name"]))
                if not is_local_station_url(row["url"]):
                    station.configured_urls.add(root_url(row["url"]))
                station.codex_status_hints.append(
                    f"status={row['status'] or ''}; last_test={row['last_test_status'] or ''}"
                )
        finally:
            con.close()

    for key, url in SCREENSHOT_ONLY_URLS.items():
        stations.setdefault(key, StationConfig(key=key, label=station_display_label(key, station_url=url))).configured_urls.add(url)
    for key, url in SITE_URL_OVERRIDES.items():
        stations.setdefault(key, StationConfig(key=key, label=station_display_label(key, station_url=url))).configured_urls.add(url)

    for key, station_type in STATION_TYPE_OVERRIDES.items():
        if key in stations:
            stations[key].station_type = station_type
    return stations


def maybe_epoch_to_iso(value: int | None) -> str:
    if value is None:
        return ""
    try:
        seconds = value / 1000 if value > 10_000_000_000 else value
        return dt.datetime.fromtimestamp(seconds).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    except (OSError, OverflowError, ValueError):
        return str(value)


def percentile(values: list[int], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def init_metric_bucket() -> dict[str, Any]:
    return {
        "requests": 0,
        "correct": 0,
        "http_2xx": 0,
        "http_200_with_error": 0,
        "nonnull_error": 0,
        "excluded_billing_errors": 0,
        "durations": [],
        "first_response_times": [],
        "first_at_raw": None,
        "last_at_raw": None,
        "suppliers": set(),
        "urls": set(),
    }


def empty_metrics_by_window() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "all_hours": {},
        "work_hours": {},
        "off_hours": {},
    }


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def log_overlap_start(created_at: int | None) -> int | None:
    if created_at is None:
        return None
    overlap = LOG_REFRESH_OVERLAP_SECONDS * 1000 if created_at > 10_000_000_000 else LOG_REFRESH_OVERLAP_SECONDS
    return max(0, created_at - overlap)


def log_key(created_at: int | None, row_id: int | None, fingerprint: str | None = None) -> str:
    base = f"{created_at}:{row_id}"
    return f"{base}:{fingerprint}" if fingerprint else base


def parse_log_key(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    created_at, row_id, *_fingerprint = value.split(":", 2)
    parsed_created_at = parse_int(created_at)
    parsed_row_id = parse_int(row_id)
    if parsed_created_at is None or parsed_row_id is None:
        return None
    return parsed_created_at, parsed_row_id


def cursor_tuple(cursor: dict[str, Any] | None) -> tuple[int, int]:
    if not isinstance(cursor, dict):
        return (-1, -1)
    return (
        parse_int(cursor.get("createdAt")) or -1,
        parse_int(cursor.get("id")) or -1,
    )


def row_cursor(row: Mapping[str, Any]) -> dict[str, int] | None:
    created_at = parse_int(row["created_at"])
    row_id = parse_int(row["id"])
    if created_at is None or row_id is None:
        return None
    return {"createdAt": created_at, "id": row_id}


def row_fingerprint(row: Mapping[str, Any]) -> str:
    payload = [
        row["supplier"] or "",
        row["url"] or "",
        row["status_code"],
        row["error"] or "",
        row["duration_ms"],
        row["first_response_ms"],
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()[:16]


def max_cursor(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, int] | None:
    if right is None:
        return left if isinstance(left, dict) else None
    if not isinstance(left, dict) or cursor_tuple(right) > cursor_tuple(left):
        return {"createdAt": cursor_tuple(right)[0], "id": cursor_tuple(right)[1]}
    return {"createdAt": cursor_tuple(left)[0], "id": cursor_tuple(left)[1]}


def metric_bucket_from_state(raw: dict[str, Any]) -> dict[str, Any]:
    item = init_metric_bucket()
    for key in (
        "requests",
        "correct",
        "http_2xx",
        "http_200_with_error",
        "nonnull_error",
        "excluded_billing_errors",
    ):
        item[key] = parse_int(raw.get(key)) or 0
    item["durations"] = [parsed for value in raw.get("durations", []) if (parsed := parse_int(value)) is not None]
    item["first_response_times"] = [
        parsed
        for value in raw.get("firstResponseTimes", raw.get("first_response_times", []))
        if (parsed := parse_int(value)) is not None
    ]
    item["first_at_raw"] = parse_int(raw.get("firstAtRaw", raw.get("first_at_raw")))
    item["last_at_raw"] = parse_int(raw.get("lastAtRaw", raw.get("last_at_raw")))
    item["suppliers"] = {
        redact_supplier_name(str(value))
        for value in raw.get("suppliers", [])
        if str(value or "").strip()
    }
    item["urls"] = {str(value) for value in raw.get("urls", []) if str(value or "").strip()}
    return item


def metric_bucket_to_state(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "requests": int(item.get("requests") or 0),
        "correct": int(item.get("correct") or 0),
        "http_2xx": int(item.get("http_2xx") or 0),
        "http_200_with_error": int(item.get("http_200_with_error") or 0),
        "nonnull_error": int(item.get("nonnull_error") or 0),
        "excluded_billing_errors": int(item.get("excluded_billing_errors") or 0),
        "durations": [parsed for value in item.get("durations", []) if (parsed := parse_int(value)) is not None],
        "firstResponseTimes": [
            parsed
            for value in item.get("first_response_times", [])
            if (parsed := parse_int(value)) is not None
        ],
        "firstAtRaw": parse_int(item.get("first_at_raw")),
        "lastAtRaw": parse_int(item.get("last_at_raw")),
        "suppliers": sorted(
            redact_supplier_name(str(value))
            for value in item.get("suppliers", set())
            if str(value or "").strip()
        ),
        "urls": sorted(str(value) for value in item.get("urls", set()) if str(value or "").strip()),
    }


def metrics_from_state(raw: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    metrics = empty_metrics_by_window()
    for window_name, station_rows in raw.items():
        if window_name not in metrics or not isinstance(station_rows, dict):
            continue
        for station_key, bucket in station_rows.items():
            if isinstance(bucket, dict):
                metrics[window_name][station_key] = metric_bucket_from_state(bucket)
    return metrics


def metrics_to_state(metrics: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        window_name: {
            station_key: metric_bucket_to_state(bucket)
            for station_key, bucket in sorted(window_metrics.items())
        }
        for window_name, window_metrics in metrics.items()
    }


def metric_station_keys(metrics: dict[str, dict[str, dict[str, Any]]]) -> set[str]:
    keys: set[str] = set()
    for window_metrics in metrics.values():
        for station_key, bucket in window_metrics.items():
            if parse_int(bucket.get("requests")) or parse_int(bucket.get("excluded_billing_errors")):
                keys.add(station_key)
    return keys


def load_log_refresh_state() -> dict[str, Any] | None:
    if not LOG_REFRESH_STATE_PATH.exists():
        return None
    try:
        payload = json.loads(LOG_REFRESH_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read log refresh state; run --full-log-rebuild only if historical logs are complete: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != LOG_REFRESH_STATE_VERSION:
        raise ValueError("Unsupported log refresh state; run --full-log-rebuild only if historical logs are complete.")
    if not isinstance(payload.get("metricsByWindow"), dict):
        raise ValueError("Log refresh state is missing metricsByWindow.")
    return payload


def trim_processed_log_keys(keys: set[str], cursor: dict[str, Any] | None) -> list[str]:
    start = log_overlap_start(cursor_tuple(cursor)[0])
    parsed: list[tuple[int, int, str]] = []
    for key in keys:
        parsed_key = parse_log_key(key)
        if parsed_key is None:
            continue
        created_at, row_id = parsed_key
        if start is not None and created_at < start:
            continue
        parsed.append((created_at, row_id, key))
    parsed.sort()
    if len(parsed) > PROCESSED_LOG_KEY_LIMIT:
        parsed = parsed[-PROCESSED_LOG_KEY_LIMIT:]
    return [key for _created_at, _row_id, key in parsed]


def write_log_refresh_state(
    metrics: dict[str, dict[str, dict[str, Any]]],
    *,
    cursor: dict[str, Any] | None,
    processed_log_keys: set[str],
    mode: str,
    rows_seen: int,
    rows_added: int,
    historical_backfill: dict[str, Any] | None = None,
) -> None:
    LOG_REFRESH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cursor_created_at, cursor_id = cursor_tuple(cursor)
    payload = {
        "version": LOG_REFRESH_STATE_VERSION,
        "generatedAt": GENERATED_AT,
        "mode": mode,
        "cursor": {
            "createdAt": cursor_created_at if cursor_created_at >= 0 else None,
            "id": cursor_id if cursor_id >= 0 else None,
        },
        "overlapSeconds": LOG_REFRESH_OVERLAP_SECONDS,
        "processedLogKeys": trim_processed_log_keys(processed_log_keys, cursor),
        "metricsByWindow": metrics_to_state(metrics),
        "lastRun": {
            "rowsSeen": rows_seen,
            "rowsAdded": rows_added,
            "historicalBackfill": historical_backfill or {"stations": [], "rowsSeen": 0, "rowsAccumulated": 0},
            "statePath": workspace_public_path(LOG_REFRESH_STATE_PATH),
        },
    }
    LOG_REFRESH_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_auto_discovered_candidate_key(key: str) -> bool:
    if key in LABELS:
        return False
    return station_key_from_public_url("https://" + key) == key


def write_request_log_station_candidates(metrics_by_window: dict[str, dict[str, dict[str, Any]]]) -> int:
    rows: list[dict[str, Any]] = []
    for key, metric in sorted(metrics_by_window.get("all_hours", {}).items()):
        if not is_auto_discovered_candidate_key(key):
            continue
        rows.append(
            {
                "host": key,
                "url": "; ".join(sorted(str(url) for url in metric.get("urls", set()) if str(url or "").strip())),
                "request_samples": metric.get("requests", 0),
                "successes": metric.get("correct", 0),
                "failures": metric.get("failures", 0),
                "first_at": metric.get("first_at", ""),
                "last_at": metric.get("last_at", ""),
                "avg_ms": metric.get("avg_ms"),
                "suppliers": "; ".join(
                    sorted(
                        redact_supplier_name(str(supplier))
                        for supplier in metric.get("suppliers", set())
                        if str(supplier or "").strip()
                    )
                ),
            }
        )
    write_csv(
        REQUEST_LOG_STATION_CANDIDATES_PATH,
        rows,
        ["host", "url", "request_samples", "successes", "failures", "first_at", "last_at", "avg_ms", "suppliers"],
    )
    return len(rows)


def is_billing_or_quota_error(error_text: Any) -> bool:
    text = str(error_text or "").strip().lower()
    if not text:
        return False

    direct_markers = (
        "requires verification before using the api",
        "verify your phone number",
        "top up $10 to unlock",
        "top up to unlock",
        "insufficient balance",
        "insufficient quota",
        "credit balance",
        "余额不足",
        "欠费",
        "充值解锁",
        "验证手机号",
    )
    if any(marker in text for marker in direct_markers):
        return True

    if "top up" in text and ("unlock" in text or "verification" in text or "verify" in text):
        return True
    return False


def time_window_for_created_at(created_at: int | None) -> str | None:
    if created_at is None:
        return None
    try:
        seconds = created_at / 1000 if created_at > 10_000_000_000 else created_at
        local_dt = dt.datetime.fromtimestamp(seconds).astimezone()
    except (OSError, OverflowError, ValueError):
        return None
    if local_dt.weekday() >= 5:
        return "off_hours"
    local_time = local_dt.time()
    return "work_hours" if WORK_HOUR_START <= local_time <= WORK_HOUR_END else "off_hours"


def finalize_metric_bucket(item: dict[str, Any]) -> None:
    requests = item["requests"]
    durations = item["durations"]
    first_response_times = item["first_response_times"]
    item["failures"] = requests - item["correct"]
    item["correct_rate"] = item["correct"] / requests if requests else None
    item["avg_ms"] = statistics.fmean(durations) if durations else None
    item["median_ms"] = percentile(durations, 0.50)
    item["p95_ms"] = percentile(durations, 0.95)
    item["avg_first_response_ms"] = statistics.fmean(first_response_times) if first_response_times else None
    item["first_at"] = maybe_epoch_to_iso(item["first_at_raw"])
    item["last_at"] = maybe_epoch_to_iso(item["last_at_raw"])


def add_request_metric(metrics_by_window: dict[str, dict[str, dict[str, Any]]], row: Mapping[str, Any]) -> bool:
    key = classify_station(row["supplier"], row["url"])
    if key is None:
        key = station_key_from_public_url(row["url"])
        if key is None:
            return False
    created_at = parse_int(row["created_at"])
    if created_at is None:
        return False
    error = row["error"]
    excluded_billing_error = is_billing_or_quota_error(error)
    target_windows = ["all_hours"]
    classified_window = time_window_for_created_at(created_at)
    if classified_window:
        target_windows.append(classified_window)

    for window_name in target_windows:
        item = metrics_by_window[window_name].setdefault(key, init_metric_bucket())
        if excluded_billing_error:
            item["excluded_billing_errors"] += 1
            continue
        item["requests"] += 1
        status_code = row["status_code"]
        is_2xx = status_code is not None and 200 <= status_code <= 299
        if is_2xx:
            item["http_2xx"] += 1
        if status_code == 200 and error is not None:
            item["http_200_with_error"] += 1
        if error is not None:
            item["nonnull_error"] += 1
        if is_2xx and error is None:
            item["correct"] += 1
        if row["duration_ms"] is not None:
            item["durations"].append(int(row["duration_ms"]))
        if row["first_response_ms"] is not None:
            item["first_response_times"].append(int(row["first_response_ms"]))
        if row["supplier"]:
            item["suppliers"].add(redact_supplier_name(row["supplier"]))
        if row["url"]:
            item["urls"].add(root_url(row["url"]))
        if item["first_at_raw"] is None or created_at < item["first_at_raw"]:
            item["first_at_raw"] = created_at
        if item["last_at_raw"] is None or created_at > item["last_at_raw"]:
            item["last_at_raw"] = created_at
    return True


def historical_public_backfill_targets(
    con: Any,
    existing_state_keys: set[str],
    *,
    log_source: str = "sqlite",
) -> dict[str, set[str]]:
    targets: dict[str, set[str]] = {}
    if log_source == "postgres":
        query = """
            select aggregate_api_supplier_name as supplier,
                   aggregate_api_url as url
            from request_log_events
            where request_type='http'
              and request_path='/v1/responses'
              and aggregate_api_url is not null
            group by aggregate_api_supplier_name, aggregate_api_url
        """
    else:
        query = """
            select aggregate_api_supplier_name as supplier,
                   aggregate_api_url as url
            from request_logs
            where request_type='http'
              and request_path='/v1/responses'
              and aggregate_api_url is not null
            group by aggregate_api_supplier_name, aggregate_api_url
        """
    for row in execute_rows(con, query, [], log_source=log_source):
        key = classify_station(row["supplier"], row["url"])
        if key is None:
            key = station_key_from_public_url(row["url"])
        if not key or key in existing_state_keys or not is_public_station_key(key):
            continue
        url = str(row["url"] or "").strip()
        if not url or is_local_station_url(url):
            continue
        targets.setdefault(key, set()).add(url)
    return targets


def backfill_historical_public_station_metrics(
    con: Any,
    metrics_by_window: dict[str, dict[str, dict[str, Any]]],
    targets: dict[str, set[str]],
    *,
    log_source: str = "sqlite",
) -> dict[str, Any]:
    if not targets:
        return {"stations": [], "rowsSeen": 0, "rowsAccumulated": 0}

    for station_key in targets:
        for window_metrics in metrics_by_window.values():
            window_metrics.pop(station_key, None)

    rows_seen = 0
    rows_accumulated = 0
    if log_source == "postgres":
        base_query = """
            select source_id as id,
                   aggregate_api_supplier_name as supplier,
                   aggregate_api_url as url,
                   status_code,
                   error,
                   duration_ms,
                   first_response_ms,
                   source_created_at as created_at
            from request_log_events
            where request_type='http'
              and request_path='/v1/responses'
              and aggregate_api_url in ({placeholders})
            order by source_created_at, source_id
        """
    else:
        base_query = """
            select id,
                   aggregate_api_supplier_name as supplier,
                   aggregate_api_url as url,
                   status_code,
                   error,
                   duration_ms,
                   first_response_ms,
                   created_at
            from request_logs
            where request_type='http'
              and request_path='/v1/responses'
              and aggregate_api_url in ({placeholders})
            order by created_at, id
        """
    for urls in targets.values():
        sorted_urls = sorted(urls)
        for start in range(0, len(sorted_urls), 400):
            chunk = sorted_urls[start : start + 400]
            placeholders = ",".join(sql_placeholder(log_source) for _ in chunk)
            query = base_query.format(placeholders=placeholders)
            for row in execute_rows(con, query, chunk, log_source=log_source):
                rows_seen += 1
                if add_request_metric(metrics_by_window, row):
                    rows_accumulated += 1

    return {
        "stations": sorted(targets),
        "rowsSeen": rows_seen,
        "rowsAccumulated": rows_accumulated,
    }


def sql_placeholder(log_source: str) -> str:
    return "%s" if log_source == "postgres" else "?"


def execute_rows(con: Any, query: str, params: list[Any] | tuple[Any, ...] | None = None, *, log_source: str = "sqlite") -> list[Any] | Any:
    if log_source == "postgres":
        with con.cursor() as cur:
            cur.execute(query, params or [])
            return cur.fetchall()
    return con.execute(query, params or [])


def request_log_connection(log_source: str) -> Any:
    if log_source == "postgres":
        return postgres_connection()
    if log_source == "sqlite":
        return db_connection()
    raise ValueError(f"Unsupported log source: {log_source}")


def request_log_query(log_source: str) -> str:
    if log_source == "postgres":
        return """
            select source_id as id,
                   aggregate_api_supplier_name as supplier,
                   aggregate_api_url as url,
                   status_code,
                   error,
                   duration_ms,
                   first_response_ms,
                   source_created_at as created_at
            from request_log_events
            where request_type='http'
              and request_path='/v1/responses'
              and (aggregate_api_supplier_name is not null or aggregate_api_url is not null)
        """
    return """
            select id,
                   aggregate_api_supplier_name as supplier,
                   aggregate_api_url as url,
                   status_code,
                   error,
                   duration_ms,
                   first_response_ms,
                   created_at
            from request_logs
            where request_type='http'
              and request_path='/v1/responses'
              and (aggregate_api_supplier_name is not null or aggregate_api_url is not null)
        """


def load_request_metrics(*, full_log_rebuild: bool = False, log_source: str = "sqlite") -> dict[str, dict[str, dict[str, Any]]]:
    global LAST_LOG_REFRESH_INFO
    state = None if full_log_rebuild else load_log_refresh_state()
    if full_log_rebuild:
        metrics_by_window = empty_metrics_by_window()
        processed_log_keys: set[str] = set()
        cursor: dict[str, Any] | None = None
        query_start: int | None = None
        existing_state_keys: set[str] = set()
        mode = "full_log_rebuild"
    elif state is None:
        metrics_by_window = empty_metrics_by_window()
        processed_log_keys = set()
        cursor = None
        query_start = None
        existing_state_keys = set()
        mode = "initialize"
    else:
        metrics_by_window = metrics_from_state(state["metricsByWindow"])
        existing_state_keys = metric_station_keys(metrics_by_window)
        processed_log_keys = {str(value) for value in state.get("processedLogKeys", [])}
        cursor = state.get("cursor") if isinstance(state.get("cursor"), dict) else None
        cursor_created_at = cursor_tuple(cursor)[0]
        query_start = log_overlap_start(cursor_created_at) if cursor_created_at >= 0 else None
        mode = "incremental"

    rows_seen = 0
    rows_added = 0
    rows_accumulated = 0
    historical_backfill = {"stations": [], "rowsSeen": 0, "rowsAccumulated": 0}
    con = request_log_connection(log_source)
    try:
        query = request_log_query(log_source)
        params: list[Any] = []
        if query_start is not None:
            query += f" and {'source_created_at' if log_source == 'postgres' else 'created_at'} >= {sql_placeholder(log_source)}"
            params.append(query_start)
        query += f" order by {'source_created_at' if log_source == 'postgres' else 'created_at'}, {'source_id' if log_source == 'postgres' else 'id'}"
        for row in execute_rows(con, query, params, log_source=log_source):
            rows_seen += 1
            current_cursor = row_cursor(row)
            if current_cursor is None:
                continue
            cursor = max_cursor(cursor, current_cursor)
            legacy_key = log_key(current_cursor["createdAt"], current_cursor["id"])
            current_key = log_key(current_cursor["createdAt"], current_cursor["id"], row_fingerprint(row))
            if current_key in processed_log_keys or legacy_key in processed_log_keys:
                continue
            processed_log_keys.add(current_key)
            rows_added += 1
            if add_request_metric(metrics_by_window, row):
                rows_accumulated += 1
        if mode == "incremental":
            historical_backfill = backfill_historical_public_station_metrics(
                con,
                metrics_by_window,
                historical_public_backfill_targets(con, existing_state_keys, log_source=log_source),
                log_source=log_source,
            )
    finally:
        con.close()

    for window_metrics in metrics_by_window.values():
        for item in window_metrics.values():
            finalize_metric_bucket(item)
    candidate_count = write_request_log_station_candidates(metrics_by_window)
    write_log_refresh_state(
        metrics_by_window,
        cursor=cursor,
        processed_log_keys=processed_log_keys,
        mode=mode,
        rows_seen=rows_seen,
        rows_added=rows_added,
        historical_backfill=historical_backfill,
    )
    LAST_LOG_REFRESH_INFO = {
        "mode": mode,
        "logSource": log_source,
        "statePath": workspace_public_path(LOG_REFRESH_STATE_PATH),
        "cursor": {
            "createdAt": cursor_tuple(cursor)[0] if cursor_tuple(cursor)[0] >= 0 else None,
            "id": cursor_tuple(cursor)[1] if cursor_tuple(cursor)[1] >= 0 else None,
        },
        "overlapSeconds": LOG_REFRESH_OVERLAP_SECONDS,
        "queryStart": query_start,
        "rowsSeen": rows_seen,
        "rowsAdded": rows_added,
        "rowsAccumulated": rows_accumulated,
        "historicalBackfill": historical_backfill,
        "candidatePath": workspace_public_path(REQUEST_LOG_STATION_CANDIDATES_PATH),
        "candidateCount": candidate_count,
        "fullRebuildWarning": (
            "Only use --full-log-rebuild when Codex Manager DB still contains complete historical request_logs."
            if full_log_rebuild
            else ""
        ),
    }
    return metrics_by_window


def ensure_metric_station_configs(
    stations: dict[str, StationConfig],
    metrics_by_window: dict[str, dict[str, dict[str, Any]]],
) -> None:
    for window_metrics in metrics_by_window.values():
        for key, metric in window_metrics.items():
            if not is_public_station_key(key):
                continue
            station = stations.setdefault(key, StationConfig(key=key, label=station_display_label(key)))
            for url in metric.get("urls", set()):
                if isinstance(url, str) and url and not is_local_station_url(url):
                    station.configured_urls.add(root_url(url))
            for supplier in metric.get("suppliers", set()):
                redacted = redact_supplier_name(str(supplier))
                if redacted:
                    station.configured_suppliers.add(redacted)


def guess_platform_one(url: str) -> dict[str, str]:
    try:
        body, final_url, status = fetch_platform_probe(url)
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        return {
            "url": url,
            "final_url": "",
            "http_status": "",
            "platform": "unknown",
            "title": "",
            "error": f"{type(exc).__name__}: {exc}",
        }

    parser = TitleParser()
    parser.feed(body)
    title = parser.title
    platform = classify_platform_html(body, title)
    if platform == "special":
        pricing_url = urllib.parse.urljoin(final_url.rstrip("/") + "/", "pricing")
        if pricing_url != final_url:
            try:
                pricing_body, pricing_final_url, pricing_status = fetch_platform_probe(pricing_url)
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError):
                pass
            else:
                pricing_parser = TitleParser()
                pricing_parser.feed(pricing_body)
                pricing_platform = classify_platform_html(pricing_body, pricing_parser.title)
                if pricing_platform != "special":
                    platform = pricing_platform
                    final_url = f"{final_url} -> {pricing_final_url}"
                    status = pricing_status
                    title = pricing_parser.title
    return {
        "url": url,
        "final_url": final_url,
        "http_status": str(status),
        "platform": platform,
        "title": title,
        "error": "",
    }


def enrich_platforms(stations: dict[str, StationConfig]) -> dict[str, dict[str, str]]:
    probes: dict[str, dict[str, str]] = {}
    tasks: dict[Any, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for key, station in stations.items():
            urls = station_urls_to_probe(station)
            if not urls:
                probes[key] = {
                    "url": "",
                    "final_url": "",
                    "http_status": "",
                    "platform": "missing-url",
                    "title": "",
                    "error": "no configured or screenshot URL",
                }
                station.platform_guess = "missing-url"
                continue
            future = pool.submit(guess_platform_one, urls[0])
            tasks[future] = (key, urls[0])
        for future in as_completed(tasks):
            key, _url = tasks[future]
            result = future.result()
            probes[key] = result
            stations[key].platform_guess = result["platform"]
    return probes


def nexus_verified_tiers() -> list[FeeTier]:
    return []


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_plain_number(value: float | None) -> str:
    parsed = parse_float(value)
    if parsed is None:
        return ""
    return str(int(parsed)) if parsed.is_integer() else f"{parsed:g}"


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "rank", "ranking"}


def parse_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "rank", "ranking"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return None


def explicitly_false(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"0", "false", "no", "n", "off", "disabled"}
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    return False


def probe_path(station: str) -> Path:
    return LIVE_AUTH_PROBE_DIR / f"{station}-live-auth-probe.json"


def load_pending_api_probes() -> dict[str, Any]:
    global PENDING_API_PROBE_CACHE
    if PENDING_API_PROBE_CACHE is not None:
        return PENDING_API_PROBE_CACHE
    if not PENDING_API_PROBE_PATH.exists():
        PENDING_API_PROBE_CACHE = {}
        return PENDING_API_PROBE_CACHE
    payload = json.loads(PENDING_API_PROBE_PATH.read_text(encoding="utf-8"))
    PENDING_API_PROBE_CACHE = payload if isinstance(payload, dict) else {}
    return PENDING_API_PROBE_CACHE


def normalize_pending_api_probe(record: dict[str, Any]) -> dict[str, Any]:
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    results = record.get("results") if isinstance(record.get("results"), dict) else {}
    probe_kind = str(record.get("probe_kind") or "").strip()
    normalized_results: dict[str, Any] = results
    if probe_kind == "new_api" and "/api/user/self/groups" in results:
        normalized_results = {"New-Api-User:pending": results}
    return {
        "location": state.get("location") or record.get("url") or "",
        "url": record.get("url") or state.get("location") or "",
        "title": state.get("title") or record.get("title") or "",
        "localStorageKeys": state.get("lsKeys") if isinstance(state.get("lsKeys"), list) else [],
        "sessionStorageKeys": [],
        "cookieNames": [],
        "uid": None,
        "user": None,
        "authUser": None,
        "authTokenLength": 0,
        "refreshTokenLength": 0,
        "hongmacodeTokenLength": 0,
        "probe_kind": probe_kind,
        "results": normalized_results,
    }


def load_live_auth_probe(station: str) -> dict[str, Any] | None:
    pending = load_pending_api_probes().get(station)
    if station in PENDING_API_PROBE_OVERRIDE_STATIONS and isinstance(pending, dict):
        return normalize_pending_api_probe(pending)
    path = probe_path(station)
    if not path.exists():
        if isinstance(pending, dict):
            return normalize_pending_api_probe(pending)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_site_data_snapshot() -> dict[str, Any]:
    if not SITE_DATA_PATH.exists():
        return {}
    try:
        payload = json.loads(SITE_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def probe_location(probe: dict[str, Any]) -> str:
    state = probe.get("state") if isinstance(probe.get("state"), dict) else {}
    for value in (probe.get("location"), probe.get("url"), state.get("location")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def body_success(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("success") is True
        or value.get("code") == 0
        or str(value.get("message") or "").lower() in {"success", "ok"}
    )


def get_probe_auth_bucket(probe: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    results = probe.get("results")
    if not isinstance(results, dict):
        return None
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key, bucket in results.items():
        if isinstance(key, str) and key.startswith("New-Api-User:") and isinstance(bucket, dict):
            candidates.append((key, bucket))
    for key, bucket in candidates:
        for path in ("/api/user/self/groups", "/api/user/topup/info", "/api/subscription/plans"):
            entry = bucket.get(path)
            body = entry.get("body") if isinstance(entry, dict) else None
            if isinstance(body, dict) and body_success(body):
                return key, bucket
        amounts = bucket.get("/api/user/amount")
        if isinstance(amounts, dict):
            for entry in amounts.values():
                body = entry.get("body") if isinstance(entry, dict) else None
                if isinstance(body, dict) and body_success(body):
                    return key, bucket
    if candidates:
        return candidates[0]
    if "/api/user/self/groups" in results and isinstance(results.get("/api/user/self/groups"), dict):
        return "direct", results
    return None


def parse_groups_from_probe(probe: dict[str, Any]) -> dict[str, dict[str, Any]]:
    auth_bucket = get_probe_auth_bucket(probe)
    if auth_bucket is None:
        return {}
    _auth_key, bucket = auth_bucket
    body = ((bucket.get("/api/user/self/groups") or {}).get("body") or {})
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def parse_topup_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    auth_bucket = get_probe_auth_bucket(probe)
    if auth_bucket is None:
        return {}
    _auth_key, bucket = auth_bucket
    body = ((bucket.get("/api/user/topup/info") or {}).get("body") or {})
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def parse_subscriptions_from_probe(probe: dict[str, Any]) -> list[dict[str, Any]]:
    auth_bucket = get_probe_auth_bucket(probe)
    if auth_bucket is None:
        return []
    _auth_key, bucket = auth_bucket
    body = ((bucket.get("/api/subscription/plans") or {}).get("body") or {})
    data = body.get("data")
    return data if isinstance(data, list) else []


def parse_amount_results_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    auth_bucket = get_probe_auth_bucket(probe)
    if auth_bucket is None:
        return {}
    _auth_key, bucket = auth_bucket
    amounts = bucket.get("/api/user/amount")
    return amounts if isinstance(amounts, dict) else {}


def krill_probe_result_body(probe: dict[str, Any], path: str) -> dict[str, Any]:
    results = probe.get("results")
    if not isinstance(results, dict):
        return {}
    result = results.get(path)
    if not isinstance(result, dict):
        return {}
    body = result.get("body")
    return body if isinstance(body, dict) else {}


def krill_routes_from_probe(probe: dict[str, Any]) -> list[dict[str, Any]]:
    data = krill_probe_result_body(probe, "/api/endpoint-settings/me").get("data")
    routes = data.get("routes") if isinstance(data, dict) else None
    return [route for route in routes if isinstance(route, dict)] if isinstance(routes, list) else []


def krill_product_payloads_from_probe(probe: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in ("/api/public/shop/products", "/api/plans"):
        body = krill_probe_result_body(probe, path)
        if body:
            payloads.append(body)
    return payloads


def krill_public_products_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    if isinstance(data, dict) and ("plans" in data or "balance_products" in data):
        return data
    if "plans" in payload or "balance_products" in payload:
        return payload
    return None


def krill_plan_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    products = krill_public_products_payload(payload)
    plans = products.get("plans") if isinstance(products, dict) else None
    return [item for item in plans if isinstance(item, dict)] if isinstance(plans, list) else []


def krill_balance_product_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    products = krill_public_products_payload(payload)
    rows = products.get("balance_products") if isinstance(products, dict) else None
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def krill_plan_is_visible_codex(plan: dict[str, Any]) -> bool:
    if explicitly_false(plan.get("active")):
        return False
    if parse_bool(plan.get("is_custom")):
        return False
    if "is_on_sale" in plan and not parse_bool(plan.get("is_on_sale")):
        return False
    allowed_provider_ids = plan.get("allowed_provider_ids")
    if isinstance(allowed_provider_ids, list) and 1 not in {int(parse_float(item) or 0) for item in allowed_provider_ids}:
        return False
    if str(plan.get("billing_type") or "").strip() != "usd_daily":
        return False
    price = parse_float(plan.get("price_usd_per_month") or plan.get("price"))
    daily_quota = parse_float(plan.get("daily_quota_usd"))
    duration_days = parse_float(plan.get("duration_days"))
    if price is None or daily_quota is None or duration_days is None:
        return False
    if price <= 0 or daily_quota <= 0 or duration_days <= 0 or price >= 10000:
        return False
    name = str(plan.get("name") or plan.get("title") or "").strip()
    return not any(marker in name for marker in ("企业", "定制", "测试", "推广", "内部"))


def krill_billing_type_from_days(days: Any) -> str:
    value = parse_float(days)
    if value == 90:
        return "quarterly"
    if value == 30:
        return "monthly"
    if value == 7:
        return "weekly"
    if value == 1:
        return "daily"
    return "monthly"


def krill_recharge_rows(probe: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for payload in krill_product_payloads_from_probe(probe):
        for plan in krill_plan_rows(payload):
            if not krill_plan_is_visible_codex(plan):
                continue
            price = parse_float(plan.get("price_usd_per_month") or plan.get("price"))
            daily_quota = parse_float(plan.get("daily_quota_usd"))
            duration_days = parse_float(plan.get("duration_days"))
            if price is None or daily_quota is None or duration_days is None:
                continue
            name = str(plan.get("name") or plan.get("title") or "Krill Codex package").strip()
            usd_amount = daily_quota * duration_days
            route_keys = plan.get("entry_route_keys")
            route_note = ""
            if isinstance(route_keys, list) and route_keys:
                route_note = "; entry routes " + ", ".join(str(item).strip() for item in route_keys if str(item).strip())
            row = {
                "name": name,
                "billing_type": krill_billing_type_from_days(duration_days),
                "rmb_amount": price,
                "usd_amount": usd_amount,
                "location": "Krill official shop Codex package API",
                "expires_rule": f"{format_plain_number(duration_days)} day package; total quota from {format_plain_number(daily_quota)} USD/day; Codex package{route_note}",
            }
            key = (row["name"], row["billing_type"], row["rmb_amount"], row["usd_amount"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
        for product in krill_balance_product_rows(payload):
            name = str(product.get("name") or product.get("title") or "Krill balance topup").strip()
            if "负余额" in name or "仅限" in name:
                continue
            rmb_amount = parse_float(product.get("price_cny") or product.get("price"))
            usd_amount = parse_float(product.get("amount_usd") or product.get("usd_amount") or product.get("usd"))
            if rmb_amount is None or usd_amount is None or rmb_amount <= 0 or usd_amount <= 0:
                continue
            row = {
                "name": name,
                "billing_type": "permanent",
                "rmb_amount": rmb_amount,
                "usd_amount": usd_amount,
                "location": "Krill official shop balance product API",
                "expires_rule": "Balance top-up; no expiry shown on shop page",
            }
            key = (row["name"], row["billing_type"], row["rmb_amount"], row["usd_amount"])
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def probe_result_body(probe: dict[str, Any], path: str) -> dict[str, Any]:
    results = probe.get("results")
    if not isinstance(results, dict):
        return {}
    result = results.get(path)
    if not isinstance(result, dict):
        return {}
    body = result.get("body")
    return body if isinstance(body, dict) else {}


def probe_result_data(probe: dict[str, Any], path: str) -> Any:
    return probe_result_body(probe, path).get("data")


def normalize_probe_multiplier(value: Any) -> float | None:
    if isinstance(value, dict):
        return parse_float(value.get("ratio"))
    return None


def normalize_probe_desc(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        desc = str(value.get("desc") or "").strip()
        if desc:
            return desc
    return fallback


def normalize_group_desc(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        for key in ("desc", "description"):
            desc = str(value.get(key) or "").strip()
            if desc:
                return desc
    return fallback


def convert_quota_to_usd(quota_value: Any) -> float | None:
    raw = parse_float(str(quota_value) if quota_value is not None else None)
    if raw is None:
        return None
    return raw / 500000.0


def estimate_plan_full_use_usd(station: str, plan: dict[str, Any]) -> float | None:
    override = parse_float(plan.get("_total_amount_usd_override"))
    if override and override > 0:
        return override
    for key in ("monthly_limit_usd", "weekly_limit_usd", "daily_limit_usd", "usd_amount", "usdAmount", "usd"):
        direct = parse_float(plan.get(key))
        if direct and direct > 0:
            if key == "daily_limit_usd":
                duration_days = parse_float(plan.get("validity_days") or plan.get("duration_value")) or 1
                return direct * max(1, duration_days)
            if key == "weekly_limit_usd":
                duration_days = parse_float(plan.get("validity_days") or plan.get("duration_value")) or 7
                return direct * max(1, int(duration_days // 7))
            return direct
    base_usd = convert_quota_to_usd(plan.get("total_amount"))
    if not base_usd:
        base_usd = convert_quota_to_usd(plan.get("quota"))
    if base_usd:
        subtitle = str(plan.get("subtitle") or "")
        if station == "17nas" and "月总额$400" in subtitle:
            return 400.0

        quota_reset_period = str(plan.get("quota_reset_period") or "").strip()
        duration_unit = str(plan.get("duration_unit") or "").strip()
        duration_value = parse_float(plan.get("duration_value")) or 0
        if quota_reset_period == "daily" and duration_unit == "day" and duration_value > 0:
            return base_usd * duration_value
        if quota_reset_period == "weekly":
            if duration_unit == "day" and duration_value > 0:
                return base_usd * max(1, int(duration_value // 7))
            if duration_unit == "month" and duration_value > 0:
                return base_usd * max(1, int(duration_value * 4))
            if duration_unit == "year" and duration_value > 0:
                return base_usd * max(1, int(duration_value * 52))
        return base_usd
    description = str(plan.get("description") or plan.get("subtitle") or plan.get("desc") or "")
    match = re.search(r"(?:\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:USD|usd|刀|美元|\$))", description)
    if match:
        parsed = parse_float(match.group(1) or match.group(2))
        if parsed and parsed > 0:
            return parsed
    return None


def plan_billing_type_and_expires(plan: dict[str, Any]) -> tuple[str, str]:
    duration_unit = str(plan.get("duration_unit") or plan.get("validity_unit") or "").strip().lower()
    duration_value = parse_float(plan.get("duration_value") or plan.get("validity_days"))
    quota_reset_period = str(plan.get("quota_reset_period") or "").strip().lower()
    billing_type = "monthly"
    expires_rule = "Subscription package"
    if duration_unit in {"month", "monthly"} and duration_value == 1:
        billing_type = "monthly"
        expires_rule = "1 month subscription"
    elif duration_unit in {"day", "days", "daily"} and duration_value == 90:
        billing_type = "quarterly"
        expires_rule = "90 day package"
    elif duration_unit in {"day", "days", "daily"} and duration_value == 30:
        billing_type = "monthly"
        expires_rule = "30 day package"
    elif duration_unit in {"day", "days", "daily"} and duration_value == 7:
        billing_type = "weekly"
        expires_rule = "7 day subscription"
    elif duration_unit in {"day", "days", "daily"} and duration_value == 1:
        billing_type = "daily"
        expires_rule = "1 day subscription"
    elif duration_unit in {"day", "days", "daily"} and duration_value == 365:
        billing_type = "yearly"
        expires_rule = "365 day package"
    elif duration_unit in {"day", "days", "daily"} and duration_value == 3:
        billing_type = "daily"
        expires_rule = "3 day package"

    if quota_reset_period == "daily":
        expires_rule += "; quota resets daily"
    elif quota_reset_period == "weekly":
        expires_rule += "; quota resets weekly"
    elif quota_reset_period == "monthly":
        expires_rule += "; quota resets monthly"
    elif quota_reset_period == "never":
        expires_rule += "; total quota pool, no periodic reset"
    return billing_type, expires_rule


def infer_station_type(
    explicit_station_type: str | None,
    *,
    has_wallet_tiers: bool,
    has_subscription_tiers: bool,
    station: str,
) -> str:
    explicit = str(explicit_station_type or "").strip()
    if explicit in STATION_TYPE_LABELS and explicit != "unknown_pending":
        return explicit
    override = STATION_TYPE_OVERRIDES.get(station)
    if override and override != "unknown_pending":
        return override
    if has_wallet_tiers and has_subscription_tiers:
        return "mixed"
    if has_subscription_tiers:
        return "subscription"
    if has_wallet_tiers:
        return "non_subscription"
    return "unknown_pending"


def plan_rows_from_data(raw_data: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_data, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw_data:
        if isinstance(item, dict):
            if isinstance(item.get("plan"), dict):
                rows.append(item["plan"])
            else:
                rows.append(item)
    return rows


def normalize_v1_plan_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    plan = dict(raw.get("plan") if isinstance(raw.get("plan"), dict) else raw)
    title = str(plan.get("title") or plan.get("name") or plan.get("product_name") or "").strip()
    price_amount = parse_float(
        plan.get("price_amount")
        or plan.get("price")
        or plan.get("amount")
        or plan.get("rmb_amount")
        or plan.get("rmbAmount")
    )
    total_amount_usd = (
        parse_float(plan.get("usd_amount") or plan.get("usdAmount") or plan.get("usd"))
        or parse_float(plan.get("monthly_limit_usd"))
        or parse_float(plan.get("weekly_limit_usd"))
        or parse_float(plan.get("daily_limit_usd"))
        or convert_quota_to_usd(plan.get("total_amount"))
        or convert_quota_to_usd(plan.get("quota"))
    )
    if total_amount_usd is None:
        description = str(plan.get("description") or plan.get("subtitle") or plan.get("desc") or "")
        match = re.search(r"(?:\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:USD|usd|刀|美元|\$))", description)
        if match:
            total_amount_usd = parse_float(match.group(1) or match.group(2))
    if not title:
        group_name = str(plan.get("group_name") or plan.get("upgrade_group") or "").strip()
        title = group_name or "subscription plan"
    if price_amount is None or price_amount <= 0:
        return None
    normalized = dict(plan)
    normalized["title"] = title
    normalized["price_amount"] = price_amount
    if total_amount_usd and total_amount_usd > 0:
        normalized["_total_amount_usd_override"] = total_amount_usd
    group_name = str(plan.get("group_name") or plan.get("upgrade_group") or "").strip()
    if group_name:
        normalized["group_name"] = group_name
        normalized["upgrade_group"] = group_name
    if "rate_multiplier" not in normalized and plan.get("group_multiplier") is not None:
        normalized["rate_multiplier"] = plan.get("group_multiplier")
    validity_days = parse_float(plan.get("validity_days"))
    if validity_days and not normalized.get("duration_value"):
        normalized["duration_unit"] = "day"
        normalized["duration_value"] = validity_days
    return normalized


def v1_plan_scope_key(plan: dict[str, Any]) -> tuple[Any, ...]:
    return (
        plan.get("id"),
        plan.get("title"),
        plan.get("price_amount"),
        plan.get("_total_amount_usd_override") or plan.get("total_amount") or plan.get("quota"),
    )


def v1_plan_has_group_scope(plan: dict[str, Any]) -> bool:
    if str(plan.get("group_name") or plan.get("upgrade_group") or "").strip():
        return True
    if isinstance(plan.get("scope_groups"), list) and plan.get("scope_groups"):
        return True
    if isinstance(plan.get("scope_multipliers"), dict) and plan.get("scope_multipliers"):
        return True
    return False


def merge_v1_plan_rows(*sources: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    scope_seen: dict[tuple[Any, ...], int] = {}
    for source in sources:
        for raw in plan_rows_from_data(source):
            if not isinstance(raw, dict):
                continue
            plan = normalize_v1_plan_row(raw)
            if not plan:
                continue
            key = (
                plan.get("id"),
                plan.get("title"),
                plan.get("price_amount"),
                plan.get("_total_amount_usd_override") or plan.get("total_amount") or plan.get("quota"),
                plan.get("group_name") or plan.get("upgrade_group"),
            )
            if key in seen:
                continue
            scope_key = v1_plan_scope_key(plan)
            existing_index = scope_seen.get(scope_key)
            if existing_index is not None:
                existing = rows[existing_index]
                if v1_plan_has_group_scope(existing) and not v1_plan_has_group_scope(plan):
                    seen.add(key)
                    continue
                if v1_plan_has_group_scope(plan) and not v1_plan_has_group_scope(existing):
                    rows[existing_index] = plan
                    seen.add(key)
                    continue
            seen.add(key)
            scope_seen[scope_key] = len(rows)
            rows.append(plan)
    return rows


def plan_applies_to_group(plan: dict[str, Any], group_name: str) -> bool:
    scope_groups = plan.get("scope_groups")
    if isinstance(scope_groups, list) and scope_groups:
        return any(
            isinstance(item, dict)
            and str(item.get("name") or "").strip() == group_name
            for item in scope_groups
        )
    scope_multipliers = plan.get("scope_multipliers")
    if isinstance(scope_multipliers, dict) and scope_multipliers:
        plan_group = str(plan.get("group_name") or plan.get("upgrade_group") or "").strip()
        return plan_group == group_name
    upgrade_group = str(plan.get("upgrade_group") or "").strip()
    if not upgrade_group:
        return True
    return upgrade_group == group_name


def plan_multiplier_for_group(plan: dict[str, Any], group_name: str, fallback: float) -> float:
    scope_groups = plan.get("scope_groups")
    if isinstance(scope_groups, list):
        for item in scope_groups:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip() != group_name:
                continue
            multiplier = parse_float(item.get("multiplier") or item.get("rate_multiplier"))
            if multiplier and multiplier > 0:
                return multiplier
    scope_multipliers = plan.get("scope_multipliers")
    group_id = str(plan.get("group_id") or "").strip()
    if isinstance(scope_multipliers, dict) and group_id:
        multiplier = parse_float(scope_multipliers.get(group_id))
        if multiplier and multiplier > 0:
            return multiplier
    return fallback


def v1_groups_from_probe(probe: dict[str, Any]) -> list[dict[str, Any]]:
    groups = probe_result_data(probe, "/api/v1/groups/available")
    return groups if isinstance(groups, list) else []


def v1_payment_config_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    data = probe_result_data(probe, "/api/v1/payment/config")
    return data if isinstance(data, dict) else {}


def v1_checkout_info_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    data = probe_result_data(probe, "/api/v1/payment/checkout-info")
    return data if isinstance(data, dict) else {}


def v1_payment_plans_from_probe(probe: dict[str, Any]) -> list[dict[str, Any]]:
    checkout_info = v1_checkout_info_from_probe(probe)
    return merge_v1_plan_rows(
        checkout_info.get("plans") if isinstance(checkout_info, dict) else None,
        probe_result_data(probe, "/api/v1/payment/plans"),
    )


def v1_live_probe_tiers(
    station: str,
    probe: dict[str, Any],
    config: dict[str, Any],
) -> list[FeeTier]:
    groups_raw = v1_groups_from_probe(probe)
    if not groups_raw:
        return []

    payment_config = v1_payment_config_from_probe(probe)
    checkout_info = v1_checkout_info_from_probe(probe)
    public_settings = probe_result_data(probe, "/api/v1/settings/public")
    public_settings = public_settings if isinstance(public_settings, dict) else {}
    plan_rows = v1_payment_plans_from_probe(probe)

    methods = checkout_info.get("methods") if isinstance(checkout_info.get("methods"), dict) else {}
    payment_methods = ", ".join(sorted(str(name) for name in methods)) or "unknown"
    balance_disabled = bool(checkout_info.get("balance_disabled", payment_config.get("balance_disabled")))
    recharge_multiplier = (
        parse_float(checkout_info.get("balance_recharge_multiplier"))
        or parse_float(payment_config.get("balance_recharge_multiplier"))
        or 0.0
    )
    recharge_fee_rate = (
        parse_float(checkout_info.get("recharge_fee_rate"))
        or parse_float(payment_config.get("recharge_fee_rate"))
        or 0.0
    )
    wallet_enabled = (
        not explicitly_false(payment_config.get("enabled"))
        and not explicitly_false(checkout_info.get("enabled"))
        and (
            not explicitly_false(public_settings.get("payment_enabled"))
            or bool(config.get("allow_public_payment_disabled_wallet"))
        )
        and not balance_disabled
        and recharge_multiplier > 0
        and (bool(methods) or bool(config.get("allow_wallet_without_methods")))
    )

    quick_amounts_raw = probe.get("quick_amounts")
    default_quick_amounts = config.get("quick_amounts") or [10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
    quick_amounts_source = quick_amounts_raw if isinstance(quick_amounts_raw, list) else default_quick_amounts
    quick_amounts = sorted(
        {
            float(amount)
            for amount in quick_amounts_source
            if isinstance(amount, (int, float, str)) and parse_float(amount) is not None and (parse_float(amount) or 0) > 0
        }
    )
    min_amount = parse_float(payment_config.get("min_amount"))
    max_amount = parse_float(payment_config.get("max_amount"))
    if min_amount is not None:
        quick_amounts = [amount for amount in quick_amounts if amount >= min_amount]
    if max_amount is not None and max_amount > 0:
        quick_amounts = [amount for amount in quick_amounts if amount <= max_amount]

    label = station_display_label(station)
    evidence_base = probe_location(probe)
    has_subscription_tiers = bool(plan_rows)
    station_type = infer_station_type(
        config.get("station_type"),
        has_wallet_tiers=wallet_enabled and bool(quick_amounts),
        has_subscription_tiers=has_subscription_tiers,
        station=station,
    )

    tiers: list[FeeTier] = []
    emitted_plan_keys: set[tuple[Any, ...]] = set()
    amount_note = "custom balance top-up"
    if min_amount is not None and max_amount and max_amount > 0:
        amount_note += f"; allowed {min_amount:g}-{max_amount:g} RMB"
    elif min_amount is not None:
        amount_note += f"; min {min_amount:g} RMB"
    amount_note += f"; checkout multiplier {recharge_multiplier:g}; recharge fee {recharge_fee_rate:g}%"

    for group in groups_raw:
        if not isinstance(group, dict):
            continue
        if str(group.get("status") or "").strip().lower() != "active":
            continue
        if str(group.get("subscription_type") or "").strip().lower() != "standard":
            continue
        group_name = str(group.get("name") or "").strip()
        if not group_name:
            continue
        group_multiplier = parse_float(group.get("rate_multiplier"))
        if group_multiplier is None or group_multiplier <= 0:
            continue
        desc = normalize_group_desc(group, group_name)

        if wallet_enabled:
            for rmb_amount in quick_amounts:
                usd_amount = rmb_amount * recharge_multiplier
                paid_rmb_amount = rmb_amount * (1 + max(recharge_fee_rate, 0.0) / 100)
                tiers.append(
                    FeeTier(
                        station=station,
                        label=label,
                        station_type=station_type,
                        group_name=group_name,
                        group_multiplier=group_multiplier,
                        recharge_name=f"wallet topup {int(rmb_amount) if rmb_amount.is_integer() else rmb_amount} RMB",
                        billing_type="permanent",
                        rmb_amount=paid_rmb_amount,
                        usd_amount=usd_amount,
                        effective_multiplier=group_multiplier * paid_rmb_amount / usd_amount if usd_amount else None,
                        recharge_location=f"payment config API + checkout API ({payment_methods})",
                        expires_rule="No expiry stated; balance top-up; RMB cost includes recharge fee"
                        if recharge_fee_rate > 0
                        else "No expiry stated; balance top-up",
                        verified=True,
                        confidence="high_tabbit_logged_in",
                        source="tabbit_logged_in_v1_group_and_payment_api",
                        evidence_url=evidence_base,
                        participates_in_verified_ranking=True,
                        notes=f"{desc}; {amount_note}",
                    )
                )

        for plan in plan_rows:
            if not isinstance(plan, dict) or not plan_applies_to_group(plan, group_name):
                continue
            effective_group_multiplier = plan_multiplier_for_group(plan, group_name, group_multiplier)
            price_amount = parse_float(plan.get("price_amount"))
            if price_amount is None:
                continue
            total_amount_usd = estimate_plan_full_use_usd(station, plan)
            if not total_amount_usd:
                continue
            title = str(plan.get("title") or "").strip() or f"{group_name} plan"
            subtitle = str(plan.get("subtitle") or "").strip()
            billing_type, expires_rule = plan_billing_type_and_expires(plan)

            emitted_plan_keys.add((title, group_name, price_amount, total_amount_usd))
            tiers.append(
                FeeTier(
                    station=station,
                    label=label,
                    station_type=station_type,
                    group_name=group_name,
                    group_multiplier=effective_group_multiplier,
                    recharge_name=title,
                    billing_type=billing_type,
                    rmb_amount=price_amount,
                    usd_amount=total_amount_usd,
                    effective_multiplier=effective_group_multiplier * price_amount / total_amount_usd if total_amount_usd else None,
                    recharge_location="payment plans API",
                    expires_rule=expires_rule,
                    verified=True,
                    confidence="high_tabbit_logged_in",
                    source="tabbit_logged_in_v1_subscription_api",
                    evidence_url=evidence_base,
                    participates_in_verified_ranking=True,
                    notes=subtitle or desc,
                )
            )
    for plan in plan_rows:
        if not isinstance(plan, dict):
            continue
        plan_group = str(plan.get("group_name") or plan.get("upgrade_group") or "").strip()
        group_multiplier = parse_float(plan.get("rate_multiplier") or plan.get("group_multiplier"))
        price_amount = parse_float(plan.get("price_amount"))
        total_amount_usd = estimate_plan_full_use_usd(station, plan)
        if not plan_group or group_multiplier is None or group_multiplier <= 0 or price_amount is None or not total_amount_usd:
            continue
        title = str(plan.get("title") or "").strip() or f"{plan_group} plan"
        emitted_key = (title, plan_group, price_amount, total_amount_usd)
        if emitted_key in emitted_plan_keys:
            continue
        billing_type, expires_rule = plan_billing_type_and_expires(plan)
        subtitle = str(plan.get("subtitle") or plan.get("description") or "").strip()
        tiers.append(
            FeeTier(
                station=station,
                label=label,
                station_type=station_type,
                group_name=plan_group,
                group_multiplier=group_multiplier,
                recharge_name=title,
                billing_type=billing_type,
                rmb_amount=price_amount,
                usd_amount=total_amount_usd,
                effective_multiplier=group_multiplier * price_amount / total_amount_usd if total_amount_usd else None,
                recharge_location="payment checkout plans API",
                expires_rule=expires_rule,
                verified=True,
                confidence="high_tabbit_logged_in",
                source="tabbit_logged_in_v1_subscription_api",
                evidence_url=evidence_base,
                participates_in_verified_ranking=True,
                notes=subtitle or f"{plan_group} plan",
            )
        )
    return tiers


def flymux_live_probe_tiers(
    station: str,
    probe: dict[str, Any],
    config: dict[str, Any],
) -> list[FeeTier]:
    groups_raw = probe_result_data(probe, "/api/v1/groups/available")
    if not isinstance(groups_raw, list):
        return []

    payment_config = probe_result_data(probe, "/api/v1/payment/config")
    checkout_info = probe_result_data(probe, "/api/v1/payment/checkout-info")
    if not isinstance(payment_config, dict) or not isinstance(checkout_info, dict):
        return []

    balance_disabled = bool(checkout_info.get("balance_disabled"))
    recharge_multiplier = (
        parse_float(checkout_info.get("balance_recharge_multiplier"))
        or parse_float(payment_config.get("balance_recharge_multiplier"))
        or 0.0
    )
    recharge_fee_rate = (
        parse_float(checkout_info.get("recharge_fee_rate"))
        or parse_float(payment_config.get("recharge_fee_rate"))
        or 0.0
    )
    if balance_disabled or recharge_multiplier <= 0 or recharge_fee_rate != 0:
        return []

    quick_amounts_raw = probe.get("quick_amounts")
    quick_amounts = quick_amounts_raw if isinstance(quick_amounts_raw, list) else list(config.get("quick_amounts") or [])
    quick_amounts = sorted(
        {
            float(amount)
            for amount in quick_amounts
            if isinstance(amount, (int, float, str)) and parse_float(amount) is not None and (parse_float(amount) or 0) > 0
        }
    )
    if not quick_amounts:
        return []

    min_amount = parse_float(payment_config.get("min_amount"))
    max_amount = parse_float(payment_config.get("max_amount"))
    methods = checkout_info.get("methods") if isinstance(checkout_info.get("methods"), dict) else {}
    payment_methods = ", ".join(sorted(str(name) for name in methods)) or "unknown"
    label = station_display_label(station)
    station_type = str(config.get("station_type") or STATION_TYPE_OVERRIDES.get(station, "unknown_pending"))
    evidence_base = probe_location(probe)
    tiers: list[FeeTier] = []

    amount_note = "UI quick presets"
    if min_amount is not None and max_amount is not None:
        amount_note += f"; custom amount allowed {min_amount:.0f}-{max_amount:.0f} RMB"
    amount_note += f"; checkout multiplier {recharge_multiplier:g}; recharge fee {recharge_fee_rate:g}%"

    for group in groups_raw:
        if not isinstance(group, dict):
            continue
        if str(group.get("status") or "").strip().lower() != "active":
            continue
        if str(group.get("subscription_type") or "").strip().lower() != "standard":
            continue
        group_name = str(group.get("name") or "").strip()
        if not group_name:
            continue
        group_multiplier = parse_float(group.get("rate_multiplier"))
        if group_multiplier is None or group_multiplier <= 0:
            continue
        desc = str(group.get("description") or "").strip() or group_name

        for rmb_amount in quick_amounts:
            usd_amount = rmb_amount * recharge_multiplier
            tiers.append(
                FeeTier(
                    station=station,
                    label=label,
                    station_type=station_type,
                    group_name=group_name,
                    group_multiplier=group_multiplier,
                    recharge_name=f"wallet topup {int(rmb_amount) if rmb_amount.is_integer() else rmb_amount} RMB",
                    billing_type="permanent",
                    rmb_amount=rmb_amount,
                    usd_amount=usd_amount,
                    effective_multiplier=group_multiplier * rmb_amount / usd_amount if usd_amount else None,
                    recharge_location=f"payment config API + checkout API ({payment_methods})",
                    expires_rule="No expiry stated; balance top-up",
                    verified=True,
                    confidence="high_tabbit_logged_in",
                    source="tabbit_logged_in_flymux_group_and_payment_api",
                    evidence_url=evidence_base,
                    participates_in_verified_ranking=True,
                    notes=f"{desc}; {amount_note}",
                    )
                )
    return tiers


def krill_live_probe_tiers(station: str, probe: dict[str, Any], config: dict[str, Any]) -> list[FeeTier]:
    routes = [
        route
        for route in krill_routes_from_probe(probe)
        if not explicitly_false(route.get("enabled")) and str(route.get("name") or route.get("key") or "").strip()
    ]
    recharges = krill_recharge_rows(probe)
    if not routes or not recharges:
        return []

    label = station_display_label(station)
    evidence_base = probe_location(probe) or SITE_URL_OVERRIDES.get(station, "")
    station_type = infer_station_type(
        config.get("station_type"),
        has_wallet_tiers=any(row["billing_type"] == "permanent" for row in recharges),
        has_subscription_tiers=any(row["billing_type"] in PACKAGE_BILLING_TYPES for row in recharges),
        station=station,
    )
    tiers: list[FeeTier] = []
    for route in routes:
        group_name = str(route.get("name") or route.get("key") or "").strip()
        route_key = str(route.get("key") or "").strip()
        desc = f"Krill route {route_key or group_name}; Codex shop page states all route multipliers are 0.2x"
        for recharge in recharges:
            usd_amount = parse_float(recharge.get("usd_amount"))
            rmb_amount = parse_float(recharge.get("rmb_amount"))
            if usd_amount is None or rmb_amount is None or usd_amount <= 0 or rmb_amount <= 0:
                continue
            tiers.append(
                FeeTier(
                    station=station,
                    label=label,
                    station_type=station_type,
                    group_name=group_name,
                    group_multiplier=KRILL_ROUTE_MULTIPLIER,
                    recharge_name=str(recharge.get("name") or "Krill recharge").strip(),
                    billing_type=str(recharge.get("billing_type") or "unknown").strip(),
                    rmb_amount=rmb_amount,
                    usd_amount=usd_amount,
                    effective_multiplier=KRILL_ROUTE_MULTIPLIER * rmb_amount / usd_amount,
                    recharge_location=str(recharge.get("location") or "Krill official shop API").strip(),
                    expires_rule=str(recharge.get("expires_rule") or "Expiry not stated").strip(),
                    verified=True,
                    confidence="high_tabbit_logged_in",
                    source="krill_logged_in_shop_and_route_api",
                    evidence_url=evidence_base,
                    participates_in_verified_ranking=True,
                    notes=desc,
                )
            )
    return tiers


def live_probe_tiers() -> list[FeeTier]:
    tiers: list[FeeTier] = []
    for station, config in LIVE_AUTH_PROBE_CONFIG.items():
        probe = load_live_auth_probe(station)
        if not probe:
            continue
        probe_type = str(config.get("probe_type") or "")
        if probe_type == "flymux_special":
            tiers.extend(flymux_live_probe_tiers(station, probe, config))
            continue
        if probe_type == "krill_special":
            tiers.extend(krill_live_probe_tiers(station, probe, config))
            continue
        if probe_type == "v1_generic":
            tiers.extend(v1_live_probe_tiers(station, probe, config))
            continue
        groups = parse_groups_from_probe(probe)
        topup = parse_topup_from_probe(probe)
        subs = parse_subscriptions_from_probe(probe)
        amounts = parse_amount_results_from_probe(probe)
        label = station_display_label(station)
        evidence_base = probe_location(probe)

        amount_options_raw = topup.get("amount_options")
        amount_options = amount_options_raw if isinstance(amount_options_raw, list) else []
        if station == "newcli" and not amount_options:
            amount_options = list(config.get("sampled_amounts") or [])
        discount_map = topup.get("discount") if isinstance(topup.get("discount"), dict) else {}
        topup_link = str(topup.get("topup_link") or "").strip()
        recharge_location = "wallet API"
        if topup_link:
            recharge_location = "wallet API -> site topup page"
        if station in KNOWN_PUBLIC_SHOP_PRODUCTS and "pay.ldxp.cn" in topup_link.lower():
            amount_options = []

        permanent_usd_map: dict[float, float] = {}
        for amount in amount_options:
            amount_key = str(int(amount)) if isinstance(amount, (int, float)) and float(amount).is_integer() else str(amount)
            amount_res = amounts.get(amount_key)
            if not amount_res or int(amount_res.get("status", 0)) != 200:
                continue
            amount_body = amount_res.get("body") if isinstance(amount_res.get("body"), dict) else {}
            usd_amount = parse_float(amount_body.get("data"))
            if usd_amount is None:
                continue
            permanent_usd_map[float(amount)] = usd_amount
        plan_rows = plan_rows_from_data(subs)
        station_type = infer_station_type(
            config.get("station_type"),
            has_wallet_tiers=bool(permanent_usd_map),
            has_subscription_tiers=bool(plan_rows),
            station=station,
        )

        for group_name, group_info in groups.items():
            group_multiplier = normalize_probe_multiplier(group_info)
            if group_multiplier is None or group_multiplier <= 0 or group_multiplier >= 10000:
                continue
            desc = normalize_probe_desc(group_info, group_name)
            participates = group_multiplier > 0
            if permanent_usd_map:
                for rmb_amount in sorted(permanent_usd_map):
                    usd_amount = permanent_usd_map[rmb_amount]
                    discount = parse_float(discount_map.get(str(int(rmb_amount)))) or parse_float(discount_map.get(str(rmb_amount))) or 1.0
                    notes = desc
                    recharge_name = f"wallet topup {int(rmb_amount) if float(rmb_amount).is_integer() else rmb_amount} RMB"
                    expires_rule = "No expiry stated in wallet API response"
                    if station == "euzhi":
                        recharge_name = f"wallet topup sample {int(rmb_amount) if float(rmb_amount).is_integer() else rmb_amount} RMB"
                        expires_rule = "Wallet API conversion sample from /api/user/amount; not a fixed package"
                        notes = f"{notes}; sampled wallet conversion, not a fixed package"
                    if discount != 1.0:
                        notes = f"{desc}; wallet discount {discount}"
                        if station == "euzhi":
                            notes = f"{desc}; wallet discount {discount}; sampled wallet conversion, not a fixed package"
                    tiers.append(
                        FeeTier(
                            station=station,
                            label=label,
                            station_type=station_type,
                            group_name=group_name,
                            group_multiplier=group_multiplier,
                            recharge_name=recharge_name,
                            billing_type="permanent",
                            rmb_amount=rmb_amount,
                            usd_amount=usd_amount,
                            effective_multiplier=group_multiplier * rmb_amount / usd_amount if usd_amount else None,
                            recharge_location=recharge_location,
                            expires_rule="No expiry stated in wallet API response",
                            verified=True,
                            confidence="high_tabbit_logged_in",
                            source="tabbit_logged_in_wallet_and_group_api",
                            evidence_url=evidence_base,
                            participates_in_verified_ranking=participates,
                            notes=notes,
                        )
                    )

            for plan in plan_rows:
                if not isinstance(plan, dict) or not plan_applies_to_group(plan, group_name):
                    continue
                effective_group_multiplier = plan_multiplier_for_group(plan, group_name, group_multiplier)
                title = str(plan.get("title") or "").strip() or f"{group_name} plan"
                subtitle = str(plan.get("subtitle") or "").strip()
                price_amount = parse_float(plan.get("price_amount"))
                if price_amount is None:
                    continue
                total_amount_usd = estimate_plan_full_use_usd(station, plan)
                if not total_amount_usd:
                    continue
                duration_unit = str(plan.get("duration_unit") or "").strip()
                duration_value = parse_float(plan.get("duration_value"))
                quota_reset_period = str(plan.get("quota_reset_period") or "").strip()
                billing_type = "monthly"
                expires_rule = "Subscription package"
                if duration_unit == "month" and duration_value == 1:
                    billing_type = "monthly"
                    expires_rule = "1 month subscription"
                elif duration_unit == "day" and duration_value == 7:
                    billing_type = "weekly"
                    expires_rule = "7 day subscription"
                elif duration_unit == "day" and duration_value == 1:
                    billing_type = "daily"
                    expires_rule = "1 day subscription"
                elif duration_unit == "day" and duration_value == 365:
                    billing_type = "yearly"
                    expires_rule = "365 day package"
                elif duration_unit == "day" and duration_value == 3:
                    billing_type = "daily"
                    expires_rule = "3 day package"

                if quota_reset_period == "daily":
                    expires_rule += "; quota resets daily"
                elif quota_reset_period == "weekly":
                    expires_rule += "; quota resets weekly"
                elif quota_reset_period == "monthly":
                    expires_rule += "; quota resets monthly"
                elif quota_reset_period == "never":
                    expires_rule += "; total quota pool, no periodic reset"

                notes = subtitle or desc
                tiers.append(
                    FeeTier(
                        station=station,
                        label=label,
                        station_type=station_type,
                        group_name=group_name,
                        group_multiplier=effective_group_multiplier,
                        recharge_name=title,
                        billing_type=billing_type,
                        rmb_amount=price_amount,
                        usd_amount=total_amount_usd,
                        effective_multiplier=effective_group_multiplier * price_amount / total_amount_usd if total_amount_usd else None,
                        recharge_location="subscription plans API",
                        expires_rule=expires_rule,
                        verified=True,
                        confidence="high_tabbit_logged_in",
                        source="tabbit_logged_in_subscription_api",
                        evidence_url=evidence_base,
                        participates_in_verified_ranking=participates,
                        notes=notes,
                    )
                )
    return tiers


def ensure_verified_input_template() -> None:
    if VERIFIED_INPUT_PATH.exists():
        return
    with VERIFIED_INPUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=VERIFIED_INPUT_FIELDNAMES)
        writer.writeheader()


def live_probe_group_multiplier(station: str, group_name: str) -> float | None:
    probe = load_live_auth_probe(station)
    if not probe:
        return None
    for item in v1_groups_from_probe(probe):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().lower() not in {"", "active"}:
            continue
        if str(item.get("name") or "").strip() != group_name:
            continue
        multiplier = parse_float(item.get("rate_multiplier"))
        if multiplier is not None and multiplier > 0:
            return multiplier
    return None


def load_verified_input_tiers(stations: dict[str, StationConfig]) -> list[FeeTier]:
    ensure_verified_input_template()
    tiers: list[FeeTier] = []
    with VERIFIED_INPUT_PATH.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            station = (row.get("station") or "").strip()
            if not station:
                continue
            label = station_display_label(station, row.get("label"))
            station_type = (row.get("station_type") or stations.get(station, StationConfig(station, label)).station_type).strip()
            group_multiplier = parse_float(row.get("group_multiplier"))
            group_name = (row.get("group_name") or "unknown").strip()
            source = (row.get("source") or "manual_tabbit_collection").strip()
            if "v1_group" in source and group_name:
                live_multiplier = live_probe_group_multiplier(station, group_name)
                if live_multiplier is not None:
                    group_multiplier = live_multiplier
            rmb_amount = parse_float(row.get("rmb_amount"))
            usd_amount = parse_float(row.get("usd_amount"))
            effective_multiplier = parse_float(row.get("effective_multiplier"))
            if effective_multiplier is None and group_multiplier is not None and rmb_amount is not None and usd_amount:
                effective_multiplier = group_multiplier * rmb_amount / usd_amount
            participates = parse_bool(row.get("participates_in_verified_ranking"), default=True)
            if effective_multiplier is not None and effective_multiplier <= 0:
                participates = False
            tiers.append(
                FeeTier(
                    station=station,
                    label=label,
                    station_type=station_type or "unknown_pending",
                    group_name=group_name,
                    group_multiplier=group_multiplier,
                    recharge_name=(row.get("recharge_name") or "unknown").strip(),
                    billing_type=(row.get("billing_type") or "unknown").strip(),
                    rmb_amount=rmb_amount,
                    usd_amount=usd_amount,
                    effective_multiplier=effective_multiplier,
                    recharge_location=(row.get("recharge_location") or "").strip(),
                    expires_rule=(row.get("expires_rule") or "").strip(),
                    verified=True,
                    confidence=(row.get("confidence") or "manual_verified").strip(),
                    source=source,
                    evidence_url=(row.get("evidence_url") or "").strip(),
                    participates_in_verified_ranking=participates,
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return tiers


def public_discovered_tiers(stations: dict[str, StationConfig]) -> list[FeeTier]:
    rows = [
        {
            "station": "atomflow.vip",
            "station_type": "non_subscription",
            "group_name": "codex",
            "group_multiplier": 0.25,
            "recharge_name": "public status 1 RMB = 1 USD credit",
            "billing_type": "permanent",
            "rmb_amount": 1.0,
            "usd_amount": 1.0,
            "recharge_location": "public /api/status + /api/pricing",
            "expires_rule": "Public status exposes quota_per_unit=500000 and price=1; expiry not stated",
            "confidence": "public_structured_evidence",
            "source": "public_status_and_pricing",
            "evidence_url": "https://atomflow.vip/api/status | https://atomflow.vip/api/pricing",
            "notes": "Public pricing exposes codex group ratio 0.25; public status implies 1 RMB maps to 1 USD quota unit. Login-page cross-check still required.",
        },
        {
            "station": "hyperapi",
            "station_type": "subscription",
            "group_name": "default",
            "group_multiplier": 1.5,
            "recharge_name": "plus monthly public package",
            "billing_type": "monthly",
            "rmb_amount": 59.90,
            "usd_amount": 480.0,
            "recharge_location": "public /api/status announcement",
            "expires_rule": "1 month; total quota 480 USD per public announcement",
            "confidence": "low_public_notice",
            "source": "public_status_and_pricing",
            "evidence_url": "https://hyperapi.cc/api/status | https://hyperapi.cc/api/pricing",
            "notes": "Public package quota plus public pricing default group ratio; login-page cross-check still required.",
        },
        {
            "station": "hyperapi",
            "station_type": "subscription",
            "group_name": "default",
            "group_multiplier": 1.5,
            "recharge_name": "lite monthly public package",
            "billing_type": "monthly",
            "rmb_amount": 39.90,
            "usd_amount": 240.0,
            "recharge_location": "public /api/status announcement",
            "expires_rule": "1 month; total quota 240 USD per public announcement",
            "confidence": "low_public_notice",
            "source": "public_status_and_pricing",
            "evidence_url": "https://hyperapi.cc/api/status | https://hyperapi.cc/api/pricing",
            "notes": "Public package quota plus public pricing default group ratio; login-page cross-check still required.",
        },
        {
            "station": "hyperapi",
            "station_type": "subscription",
            "group_name": "default",
            "group_multiplier": 1.5,
            "recharge_name": "weekly public package",
            "billing_type": "weekly",
            "rmb_amount": 15.90,
            "usd_amount": 120.0,
            "recharge_location": "public /api/status announcement",
            "expires_rule": "7 days; total quota 120 USD per public announcement",
            "confidence": "low_public_notice",
            "source": "public_status_and_pricing",
            "evidence_url": "https://hyperapi.cc/api/status | https://hyperapi.cc/api/pricing",
            "notes": "Public package quota plus public pricing default group ratio; login-page cross-check still required.",
        },
        {
            "station": "hyperapi",
            "station_type": "subscription",
            "group_name": "default",
            "group_multiplier": 1.5,
            "recharge_name": "daily public package",
            "billing_type": "daily",
            "rmb_amount": 2.90,
            "usd_amount": 20.0,
            "recharge_location": "public /api/status announcement",
            "expires_rule": "1 day; total quota 20 USD per public announcement",
            "confidence": "low_public_notice",
            "source": "public_status_and_pricing",
            "evidence_url": "https://hyperapi.cc/api/status | https://hyperapi.cc/api/pricing",
            "notes": "Public package quota plus public pricing default group ratio; login-page cross-check still required.",
        },
        {
            "station": "17nas",
            "station_type": "mixed",
            "group_name": "default",
            "group_multiplier": 0.3,
            "recharge_name": "public 1:1 USD topup",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 10.0,
            "recharge_location": "public pricing page",
            "expires_rule": "1:1 USD recharge; min 10 RMB per public pricing page",
            "confidence": "low_public_notice",
            "source": "public_status_and_pricing_page",
            "evidence_url": "https://api.17nas.com/api/status | https://api.17nas.com/tools/pricing/",
            "notes": "Default group ratio from public status; 1:1 USD recharge from public pricing page; login-page cross-check still required.",
        },
        {
            "station": "17nas",
            "station_type": "mixed",
            "group_name": "vip",
            "group_multiplier": 0.5,
            "recharge_name": "public 1:1 USD topup",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 10.0,
            "recharge_location": "public pricing page",
            "expires_rule": "1:1 USD recharge; min 10 RMB per public pricing page",
            "confidence": "low_public_notice",
            "source": "public_status_and_pricing_page",
            "evidence_url": "https://api.17nas.com/api/status | https://api.17nas.com/tools/pricing/",
            "notes": "VIP Claude reverse ratio from public status; 1:1 USD recharge from public pricing page; login-page cross-check still required.",
        },
        {
            "station": "bytecat",
            "station_type": "non_subscription",
            "group_name": "福利分组",
            "group_multiplier": 0.1,
            "recharge_name": "public homepage 1 RMB = 1 USD recharge",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 10.0,
            "recharge_location": "public homepage announcement",
            "expires_rule": "Recharge min 10 RMB; expiry not stated publicly",
            "confidence": "low_public_notice",
            "source": "public_homepage_and_pricing",
            "evidence_url": "https://codecdn.bytecatcode.org/ | https://codecdn.bytecatcode.org/api/pricing",
            "notes": "Recharge statement from public homepage; group ratio from public pricing; login-page cross-check still required.",
        },
        {
            "station": "bytecat",
            "station_type": "non_subscription",
            "group_name": "codex",
            "group_multiplier": 0.3,
            "recharge_name": "public homepage 1 RMB = 1 USD recharge",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 10.0,
            "recharge_location": "public homepage announcement",
            "expires_rule": "Recharge min 10 RMB; expiry not stated publicly",
            "confidence": "low_public_notice",
            "source": "public_homepage_and_pricing",
            "evidence_url": "https://codecdn.bytecatcode.org/ | https://codecdn.bytecatcode.org/api/pricing",
            "notes": "Recharge statement from public homepage; group ratio from public pricing; login-page cross-check still required.",
        },
        {
            "station": "bytecat",
            "station_type": "non_subscription",
            "group_name": "codex-pro",
            "group_multiplier": 0.4,
            "recharge_name": "public homepage 1 RMB = 1 USD recharge",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 10.0,
            "recharge_location": "public homepage announcement",
            "expires_rule": "Recharge min 10 RMB; expiry not stated publicly",
            "confidence": "low_public_notice",
            "source": "public_homepage_and_pricing",
            "evidence_url": "https://codecdn.bytecatcode.org/ | https://codecdn.bytecatcode.org/api/pricing",
            "notes": "Recharge statement from public homepage; group ratio from public pricing; login-page cross-check still required.",
        },
        {
            "station": "bytecat",
            "station_type": "non_subscription",
            "group_name": "codex-fast",
            "group_multiplier": 0.5,
            "recharge_name": "public homepage 1 RMB = 1 USD recharge",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 10.0,
            "recharge_location": "public homepage announcement",
            "expires_rule": "Recharge min 10 RMB; expiry not stated publicly",
            "confidence": "low_public_notice",
            "source": "public_homepage_and_pricing",
            "evidence_url": "https://codecdn.bytecatcode.org/ | https://codecdn.bytecatcode.org/api/pricing",
            "notes": "Recharge statement from public homepage; group ratio from public pricing; login-page cross-check still required.",
        },
        {
            "station": "newcli",
            "station_type": "non_subscription",
            "group_name": "codex",
            "group_multiplier": 0.1,
            "recharge_name": "public homepage codex price 0.1 RMB per USD",
            "billing_type": "permanent_or_unknown",
            "rmb_amount": 1.0,
            "usd_amount": 1.0,
            "recharge_location": "public homepage announcement",
            "expires_rule": "Expiry not stated publicly",
            "confidence": "low_public_notice_inferred_recharge",
            "source": "public_homepage_and_pricing",
            "evidence_url": "https://business.newcli.com/ | https://business.newcli.com/api/pricing",
            "notes": "Public announcement states final codex price 0.1 RMB per USD; recharge conversion is inferred rather than separately shown; login-page cross-check still required.",
        },
    ]
    tiers: list[FeeTier] = []
    for row in rows:
        station = row["station"]
        label = station_display_label(station, stations.get(station, StationConfig(station, station_display_label(station))).label)
        effective = row["group_multiplier"] * row["rmb_amount"] / row["usd_amount"]
        tiers.append(
            FeeTier(
                station=station,
                label=label,
                station_type=row["station_type"],
                group_name=row["group_name"],
                group_multiplier=row["group_multiplier"],
                recharge_name=row["recharge_name"],
                billing_type=row["billing_type"],
                rmb_amount=row["rmb_amount"],
                usd_amount=row["usd_amount"],
                effective_multiplier=effective,
                recharge_location=row["recharge_location"],
                expires_rule=row["expires_rule"],
                verified=True,
                confidence=row["confidence"],
                source=row["source"],
                evidence_url=row["evidence_url"],
                participates_in_verified_ranking=True,
                notes=row["notes"],
            )
        )
    return tiers


KNOWN_PUBLIC_SHOP_PRODUCTS: dict[str, list[dict[str, Any]]] = {
    "lumibest": [
        {"name": "Lumi API 10 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 10.0, "usd_amount": 10.0, "expires_rule": "External shop redeem code; shop exposes price only, quota defaults to 1 RMB = 1 USD"},
        {"name": "Lumi API 50 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 50.0, "usd_amount": 50.0, "expires_rule": "External shop redeem code; shop exposes price only, quota defaults to 1 RMB = 1 USD"},
        {"name": "Lumi API 100 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 100.0, "usd_amount": 100.0, "expires_rule": "External shop redeem code; shop exposes price only, quota defaults to 1 RMB = 1 USD"},
    ],
    "hello-code": [
        {"name": "Codex plus/team 10 USD redeem code", "billing_type": "permanent", "rmb_amount": 10.0, "usd_amount": 10.0, "expires_rule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
        {"name": "Codex plus/team 30 USD redeem code", "billing_type": "permanent", "rmb_amount": 30.0, "usd_amount": 30.0, "expires_rule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
        {"name": "Codex plus/team 50 USD redeem code", "billing_type": "permanent", "rmb_amount": 50.0, "usd_amount": 50.0, "expires_rule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
        {"name": "Codex plus/team 100 USD redeem code", "billing_type": "permanent", "rmb_amount": 100.0, "usd_amount": 100.0, "expires_rule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
    ],
    "dogcoding": [
        {"name": "20 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 6.0, "usd_amount": 20.0},
        {"name": "30 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 9.0, "usd_amount": 30.0},
        {"name": "50 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 15.0, "usd_amount": 50.0},
        {"name": "100 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 30.0, "usd_amount": 100.0},
        {"name": "200 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 60.0, "usd_amount": 200.0},
        {"name": "500 USD external shop redeem code", "billing_type": "permanent", "rmb_amount": 145.0, "usd_amount": 500.0},
    ],
    "585016d3.u3u.dev": [
        {"name": "weekly card 300 USD quota", "billing_type": "weekly", "rmb_amount": 28.0, "usd_amount": 300.0},
        {"name": "weekly card 500 USD quota", "billing_type": "weekly", "rmb_amount": 48.0, "usd_amount": 500.0},
        {"name": "monthly card 1200 USD quota", "billing_type": "monthly", "rmb_amount": 88.0, "usd_amount": 1200.0},
        {"name": "monthly card 2500 USD quota", "billing_type": "monthly", "rmb_amount": 178.0, "usd_amount": 2500.0},
        {"name": "monthly card 5000 USD quota", "billing_type": "monthly", "rmb_amount": 358.0, "usd_amount": 5000.0},
        {"name": "quarterly card 10000 USD quota", "billing_type": "quarterly", "rmb_amount": 588.0, "usd_amount": 10000.0},
        {"name": "quarterly card 20000 USD quota", "billing_type": "quarterly", "rmb_amount": 1188.0, "usd_amount": 20000.0},
        {"name": "100 USD permanent quota", "billing_type": "permanent", "rmb_amount": 20.0, "usd_amount": 100.0},
        {"name": "200 USD permanent quota", "billing_type": "permanent", "rmb_amount": 36.0, "usd_amount": 200.0},
        {"name": "300 USD permanent quota", "billing_type": "permanent", "rmb_amount": 50.0, "usd_amount": 300.0},
    ],
    "zhishu.dev": [
        {"name": "Codex API 10 USD permanent quota", "billing_type": "permanent", "rmb_amount": 10.0, "usd_amount": 10.0, "expires_rule": "External shop redeem code; product states Codex API 10 USD quota with no expiry"},
        {"name": "Codex API 20 USD permanent quota", "billing_type": "permanent", "rmb_amount": 19.0, "usd_amount": 20.0, "expires_rule": "External shop redeem code; product states Codex API 20 USD quota with no expiry"},
        {"name": "Codex API 50 USD permanent quota", "billing_type": "permanent", "rmb_amount": 45.0, "usd_amount": 50.0, "expires_rule": "External shop redeem code; product states Codex API 50 USD quota with no expiry"},
        {"name": "Codex monthly Plus 300 USD quota", "billing_type": "monthly", "rmb_amount": 240.0, "usd_amount": 300.0, "expires_rule": "30 day external shop package; detail states 20 USD/day, 100 USD/week, 300 USD/month"},
        {"name": "Codex monthly Pro 500 USD quota", "billing_type": "monthly", "rmb_amount": 350.0, "usd_amount": 500.0, "expires_rule": "30 day external shop package; detail states 30 USD/day, 150 USD/week, 500 USD/month"},
    ],
}


KNOWN_PUBLIC_SHOP_META: dict[str, dict[str, Any]] = {
    "lumibest": {
        "station_type": "non_subscription",
        "evidence_url": "https://pay.ldxp.cn/shop/WE9ZBUQG",
        "recharge_location": "official external pay.ldxp.cn shop redeem code",
        "expires_rule": "External shop redeem code; shop exposes price only, quota defaults to 1 RMB = 1 USD",
        "notes": "LumiBest wallet topup link points to the official pay.ldxp.cn shop. The shop exposes 10/50/100 RMB payment products but no explicit quota field, so the project policy defaults those products to 1 RMB = 1 USD quota.",
    },
    "hello-code": {
        "station_type": "non_subscription",
        "evidence_url": "https://pay.ldxp.cn/shop/SAIS2N05",
        "recharge_location": "official external pay.ldxp.cn shop redeem code",
        "expires_rule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station",
        "notes": "HelloCode payment config is disabled, but the logged-in Recharge/Subscription menu embeds the official pay.ldxp.cn shop. Browser verification found 10/30/50/100 USD Codex plus/team redeem-code products and a payable order dialog.",
        "group_allowlist": ["codex-plus"],
    },
    "dogcoding": {
        "station_type": "non_subscription",
        "evidence_url": "https://pay.ldxp.cn/shop/JVDCG8IG",
        "recharge_location": "official external pay.ldxp.cn shop redeem code",
        "expires_rule": "External shop redeem code; permanent balance unless product name states otherwise",
        "notes": "Payment config is disabled in the v1 site; use the official menu-linked external shop instead of generated wallet presets.",
    },
    "585016d3.u3u.dev": {
        "station_type": "mixed",
        "evidence_url": "https://pay.ldxp.cn/shop/u3u",
        "recharge_location": "official external pay.ldxp.cn shop redeem code",
        "expires_rule": "External shop redeem code; package validity follows product name",
        "notes": "Public site config points to the external shop; shop description says quota follows official 1:1 standard. Login-page cross-check still required.",
    },
    "zhishu.dev": {
        "station_type": "mixed",
        "evidence_url": "https://pay.ldxp.cn/shop/CFUOS364/ek8gty",
        "recharge_location": "official external pay.ldxp.cn shop redeem code",
        "expires_rule": "External shop redeem code; package validity follows product detail",
        "notes": "zhishu.dev payment config is disabled; the official menu-linked pay.ldxp.cn shop was verified in the logged-in browser and exposes Codex API quota plus monthly packages.",
    },
}


def known_public_shop_groups(station: str) -> list[tuple[str, float, str]]:
    probe = load_live_auth_probe(station)
    groups: list[tuple[str, float, str]] = []
    group_allowlist = {
        str(name).strip()
        for name in KNOWN_PUBLIC_SHOP_META.get(station, {}).get("group_allowlist", [])
        if str(name).strip()
    }
    if probe:
        for item in v1_groups_from_probe(probe):
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "").strip().lower() != "active":
                continue
            if str(item.get("subscription_type") or "").strip().lower() not in {"", "standard"}:
                continue
            group_name = str(item.get("name") or "").strip()
            multiplier = parse_float(item.get("rate_multiplier"))
            if group_name and multiplier and multiplier > 0:
                groups.append((group_name, multiplier, normalize_group_desc(item, group_name)))
    if not groups and probe:
        for group_name, group_info in parse_groups_from_probe(probe).items():
            group_name = str(group_name or "").strip()
            multiplier = normalize_probe_multiplier(group_info)
            if group_name and multiplier and multiplier > 0:
                groups.append((group_name, multiplier, normalize_probe_desc(group_info, group_name)))
    if groups:
        if group_allowlist:
            filtered = [group for group in groups if group[0] in group_allowlist]
            if filtered:
                return filtered
        return groups
    return [("default", 1.0, "default")]


def known_public_shop_tiers(stations: dict[str, StationConfig]) -> list[FeeTier]:
    tiers: list[FeeTier] = []
    for station, products in KNOWN_PUBLIC_SHOP_PRODUCTS.items():
        meta = KNOWN_PUBLIC_SHOP_META[station]
        label = station_display_label(station, stations.get(station, StationConfig(station, station_display_label(station))).label)
        for group_name, group_multiplier, group_note in known_public_shop_groups(station):
            for product in products:
                rmb_amount = parse_float(product.get("rmb_amount"))
                usd_amount = parse_float(product.get("usd_amount"))
                if rmb_amount is None or usd_amount is None or usd_amount <= 0:
                    continue
                billing_type = str(product.get("billing_type") or "permanent")
                expires_rule = str(product.get("expires_rule") or meta["expires_rule"])
                if billing_type == "weekly":
                    expires_rule = "7 day external shop redeem code package"
                elif billing_type == "monthly" and not product.get("expires_rule"):
                    expires_rule = "30 day external shop redeem code package"
                elif billing_type == "quarterly":
                    expires_rule = "90 day external shop redeem code package"
                tiers.append(
                    FeeTier(
                        station=station,
                        label=label,
                        station_type=meta["station_type"],
                        group_name=group_name,
                        group_multiplier=group_multiplier,
                        recharge_name=str(product["name"]),
                        billing_type=billing_type,
                        rmb_amount=rmb_amount,
                        usd_amount=usd_amount,
                        effective_multiplier=group_multiplier * rmb_amount / usd_amount,
                        recharge_location=meta["recharge_location"],
                        expires_rule=expires_rule,
                        verified=True,
                        confidence="public_external_shop_verified",
                        source="public_external_shop_redeem_code",
                        evidence_url=meta["evidence_url"],
                        participates_in_verified_ranking=True,
                        notes=f"{group_note}; {meta['notes']}",
                    )
                )
    return tiers


def special_verified_tiers(stations: dict[str, StationConfig]) -> list[FeeTier]:
    rows = [
        {
            "station": "gettoken",
            "station_type": "non_subscription",
            "group_name": "官方 API 1:1",
            "group_multiplier": 1.0,
            "recharge_name": "基础充值套餐",
            "billing_type": "permanent",
            "rmb_amount": 50.0,
            "usd_amount": 200.0,
            "recharge_location": "公开定价页 + 登录控制台",
            "expires_rule": "永久额度；定价页说明永久有效、不清零、无日限周限月限；按官网模型价格 1:1 扣减",
            "confidence": "manual_verified",
            "source": "tabbit_logged_in_console_and_public_pricing_page",
            "evidence_url": "https://gettoken.dev/zh-CN/pricing | https://gettoken.dev/zh-CN/console/plans | https://gettoken.dev/zh-CN/console/api-keys",
            "notes": "控制台与公开定价页均显示固定官方 API 套餐；不区分额外折扣分组。",
        },
        {
            "station": "gettoken",
            "station_type": "non_subscription",
            "group_name": "官方 API 1:1",
            "group_multiplier": 1.0,
            "recharge_name": "500美金额度",
            "billing_type": "permanent",
            "rmb_amount": 100.0,
            "usd_amount": 500.0,
            "recharge_location": "公开定价页 + 登录控制台",
            "expires_rule": "永久额度；定价页说明永久有效、不清零、无日限周限月限；按官网模型价格 1:1 扣减",
            "confidence": "manual_verified",
            "source": "tabbit_logged_in_console_and_public_pricing_page",
            "evidence_url": "https://gettoken.dev/zh-CN/pricing | https://gettoken.dev/zh-CN/console/plans | https://gettoken.dev/zh-CN/console/api-keys",
            "notes": "控制台与公开定价页均显示固定官方 API 套餐；不区分额外折扣分组。",
        },
        {
            "station": "gettoken",
            "station_type": "non_subscription",
            "group_name": "官方 API 1:1",
            "group_multiplier": 1.0,
            "recharge_name": "进阶充值套餐",
            "billing_type": "permanent",
            "rmb_amount": 200.0,
            "usd_amount": 1000.0,
            "recharge_location": "公开定价页 + 登录控制台",
            "expires_rule": "永久额度；定价页说明永久有效、不清零、无日限周限月限；按官网模型价格 1:1 扣减",
            "confidence": "manual_verified",
            "source": "tabbit_logged_in_console_and_public_pricing_page",
            "evidence_url": "https://gettoken.dev/zh-CN/pricing | https://gettoken.dev/zh-CN/console/plans | https://gettoken.dev/zh-CN/console/api-keys",
            "notes": "控制台与公开定价页均显示固定官方 API 套餐；不区分额外折扣分组。",
        },
        {
            "station": "gettoken",
            "station_type": "non_subscription",
            "group_name": "官方 API 1:1",
            "group_multiplier": 1.0,
            "recharge_name": "旗舰充值套餐",
            "billing_type": "permanent",
            "rmb_amount": 350.0,
            "usd_amount": 2000.0,
            "recharge_location": "公开定价页 + 登录控制台",
            "expires_rule": "永久额度；定价页说明永久有效、不清零、无日限周限月限；按官网模型价格 1:1 扣减",
            "confidence": "manual_verified",
            "source": "tabbit_logged_in_console_and_public_pricing_page",
            "evidence_url": "https://gettoken.dev/zh-CN/pricing | https://gettoken.dev/zh-CN/console/plans | https://gettoken.dev/zh-CN/console/api-keys",
            "notes": "控制台与公开定价页均显示固定官方 API 套餐；不区分额外折扣分组。",
        },
        {
            "station": "gettoken",
            "station_type": "non_subscription",
            "group_name": "官方 API 1:1",
            "group_multiplier": 1.0,
            "recharge_name": "5000美金额度",
            "billing_type": "permanent",
            "rmb_amount": 700.0,
            "usd_amount": 5000.0,
            "recharge_location": "公开定价页 + 登录控制台",
            "expires_rule": "永久额度；定价页说明永久有效、不清零、无日限周限月限；按官网模型价格 1:1 扣减",
            "confidence": "manual_verified",
            "source": "tabbit_logged_in_console_and_public_pricing_page",
            "evidence_url": "https://gettoken.dev/zh-CN/pricing | https://gettoken.dev/zh-CN/console/plans | https://gettoken.dev/zh-CN/console/api-keys",
            "notes": "控制台与公开定价页均显示固定官方 API 套餐；不区分额外折扣分组。",
        },
    ]
    tiers: list[FeeTier] = []
    for row in rows:
        station = row["station"]
        label = station_display_label(station, stations.get(station, StationConfig(station, station_display_label(station))).label)
        effective = row["group_multiplier"] * row["rmb_amount"] / row["usd_amount"]
        tiers.append(
            FeeTier(
                station=station,
                label=label,
                station_type=row["station_type"],
                group_name=row["group_name"],
                group_multiplier=row["group_multiplier"],
                recharge_name=row["recharge_name"],
                billing_type=row["billing_type"],
                rmb_amount=row["rmb_amount"],
                usd_amount=row["usd_amount"],
                effective_multiplier=effective,
                recharge_location=row["recharge_location"],
                expires_rule=row["expires_rule"],
                verified=True,
                confidence=row["confidence"],
                source=row["source"],
                evidence_url=row["evidence_url"],
                participates_in_verified_ranking=True,
                notes=row["notes"],
            )
        )
    return tiers


def freemodel_verified_tiers(stations: dict[str, StationConfig]) -> list[FeeTier]:
    rows = [
        {
            "station": "freemodel",
            "station_type": "mixed",
            "group_name": "default",
            "group_multiplier": 1.0,
            "recharge_name": "Pro 月卡",
            "billing_type": "monthly",
            "rmb_amount": 20.0,
            "usd_amount": 6667 / 100 * 30 / 7,
            "recharge_location": "站内账单页 + 站内用量页",
            "expires_rule": "按 30 天满额使用折算；7 天额度上限 66.67 美元；1 个月订阅；手动续费，不自动扣款",
            "confidence": "manual_verified",
            "source": "user_confirmed_multiplier_plus_live_billing_api",
            "evidence_url": "https://freemodel.dev/dashboard | https://freemodel.dev/dashboard/billing | https://freemodel.dev/dashboard/usage",
            "notes": "用户确认 freemodel 充值倍率=1、分组倍率=1；站内账单 API 显示 Pro 方案价格 20、周额度上限 66.67 美元。",
        },
        {
            "station": "freemodel",
            "station_type": "mixed",
            "group_name": "default",
            "group_multiplier": 1.0,
            "recharge_name": "Max 100 月卡",
            "billing_type": "monthly",
            "rmb_amount": 100.0,
            "usd_amount": 33333 / 100 * 30 / 7,
            "recharge_location": "站内账单页 + 站内用量页",
            "expires_rule": "按 30 天满额使用折算；7 天额度上限 333.33 美元；1 个月订阅；手动续费，不自动扣款",
            "confidence": "manual_verified",
            "source": "user_confirmed_multiplier_plus_live_billing_api",
            "evidence_url": "https://freemodel.dev/dashboard | https://freemodel.dev/dashboard/billing | https://freemodel.dev/dashboard/usage",
            "notes": "用户确认 freemodel 充值倍率=1、分组倍率=1；站内账单 API 显示 Max 100 方案价格 100、周额度上限 333.33 美元。",
        },
        {
            "station": "freemodel",
            "station_type": "mixed",
            "group_name": "default",
            "group_multiplier": 1.0,
            "recharge_name": "Max 200 月卡",
            "billing_type": "monthly",
            "rmb_amount": 200.0,
            "usd_amount": 66667 / 100 * 30 / 7,
            "recharge_location": "站内账单页 + 站内用量页",
            "expires_rule": "按 30 天满额使用折算；7 天额度上限 666.67 美元；1 个月订阅；手动续费，不自动扣款",
            "confidence": "manual_verified",
            "source": "user_confirmed_multiplier_plus_live_billing_api",
            "evidence_url": "https://freemodel.dev/dashboard | https://freemodel.dev/dashboard/billing | https://freemodel.dev/dashboard/usage",
            "notes": "用户确认 freemodel 充值倍率=1、分组倍率=1；站内账单 API 显示 Max 200 方案价格 200、周额度上限 666.67 美元。",
        },
        {
            "station": "freemodel",
            "station_type": "mixed",
            "group_name": "default",
            "group_multiplier": 1.0,
            "recharge_name": "自定义充值（最低 10 刀；余额上限 1000 刀）",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 10.0,
            "recharge_location": "站内用量页 -> 立即充值 -> Stripe",
            "expires_rule": "用户确认充值倍率=1；最低充值 10 刀解锁 VIP 线路；未注明有效期",
            "confidence": "manual_verified",
            "source": "user_confirmed_multiplier_plus_live_billing_api",
            "evidence_url": "https://freemodel.dev/dashboard | https://freemodel.dev/dashboard/usage",
            "notes": "用户确认 freemodel 充值倍率=1、分组倍率=1；页面显示充值 10 刀或以上可解锁 VIP 高速线路，额外余额上限 1000 刀。",
        },
    ]
    tiers: list[FeeTier] = []
    for row in rows:
        station = row["station"]
        label = station_display_label(station, stations.get(station, StationConfig(station, station_display_label(station))).label)
        effective = row["group_multiplier"] * row["rmb_amount"] / row["usd_amount"]
        tiers.append(
            FeeTier(
                station=station,
                label=label,
                station_type=row["station_type"],
                group_name=row["group_name"],
                group_multiplier=row["group_multiplier"],
                recharge_name=row["recharge_name"],
                billing_type=row["billing_type"],
                rmb_amount=row["rmb_amount"],
                usd_amount=row["usd_amount"],
                effective_multiplier=effective,
                recharge_location=row["recharge_location"],
                expires_rule=row["expires_rule"],
                verified=True,
                confidence=row["confidence"],
                source=row["source"],
                evidence_url=row["evidence_url"],
                participates_in_verified_ranking=True,
                notes=row["notes"],
            )
        )
    return tiers


def site_data_station_records() -> dict[str, dict[str, Any]]:
    stations = load_site_data_snapshot().get("stations")
    if not isinstance(stations, list):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for item in stations:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key:
            records[key] = item
    return records


def detail_record_tiers(stations: dict[str, StationConfig]) -> list[FeeTier]:
    records = site_data_station_records()
    tiers: list[FeeTier] = []
    for station, record in records.items():
        if station not in DETAIL_EVIDENCE_FEE_STATIONS:
            continue
        groups = record.get("groupMultipliers")
        recharges = record.get("rechargeTiers")
        if not isinstance(groups, list) or not isinstance(recharges, list) or not groups or not recharges:
            continue
        meta = DETAIL_EVIDENCE_FEE_META.get(station, {})
        label = station_display_label(station, record.get("label") or stations.get(station, StationConfig(station, station_display_label(station))).label)
        station_type = str(record.get("stationType") or stations.get(station, StationConfig(station, label)).station_type)
        if station_type not in STATION_TYPE_LABELS or station_type == "unknown_pending":
            station_type = STATION_TYPE_OVERRIDES.get(station, "unknown_pending")
        evidence_url = str(record.get("url") or SITE_URL_OVERRIDES.get(station) or "").strip()
        tier_notes = record.get("tierNotes")
        note_parts: list[str] = []
        for item in [meta.get("notes")]:
            note = str(item or "").strip()
            if note and note not in note_parts:
                note_parts.append(note)
        if isinstance(tier_notes, list):
            for item in tier_notes:
                note = str(item or "").strip()
                if not note:
                    continue
                for segment in re.split(r";\s+", note):
                    segment = segment.strip()
                    if segment and segment not in note_parts:
                        note_parts.append(segment)
        notes = "; ".join(note_parts)
        confidence = str(meta.get("confidence") or "public_structured_evidence")
        source = str(meta.get("source") or "detail_page_structured_evidence")
        meta_group_rows = meta.get("groupRows")
        tier_groups = meta_group_rows if isinstance(meta_group_rows, list) and meta_group_rows else groups
        for group in tier_groups:
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("groupName") or group.get("group_name") or "").strip()
            group_multiplier = parse_float(group.get("groupMultiplier") or group.get("group_multiplier"))
            if not group_name or group_multiplier is None or group_multiplier <= 0:
                continue
            codex_eligible = parse_optional_bool(
                group.get("codexEligible") if "codexEligible" in group else group.get("codex_eligible")
            )
            usage_label = str(group.get("usageLabel") or group.get("usage_label") or "").strip()
            for recharge in recharges:
                if not isinstance(recharge, dict):
                    continue
                recharge_name = str(recharge.get("rechargeName") or recharge.get("recharge_name") or "").strip()
                billing_type = str(recharge.get("billingType") or recharge.get("billing_type") or "unknown").strip() or "unknown"
                rmb_amount = parse_float(recharge.get("rmbAmount") or recharge.get("rmb_amount"))
                usd_amount = parse_float(recharge.get("usdAmount") or recharge.get("usd_amount"))
                if not recharge_name or rmb_amount is None or usd_amount is None or usd_amount <= 0:
                    continue
                effective = group_multiplier * rmb_amount / usd_amount
                tier_note_parts = list(note_parts)
                if codex_eligible is False:
                    tier_note_parts.append("codexEligible=false")
                elif codex_eligible is True:
                    tier_note_parts.append("codexEligible=true")
                if usage_label:
                    tier_note_parts.append(f"usage={usage_label}")
                tiers.append(
                    FeeTier(
                        station=station,
                        label=label,
                        station_type=station_type,
                        group_name=group_name,
                        group_multiplier=group_multiplier,
                        recharge_name=recharge_name,
                        billing_type=billing_type,
                        rmb_amount=rmb_amount,
                        usd_amount=usd_amount,
                        effective_multiplier=effective,
                        recharge_location=str(recharge.get("rechargeLocation") or recharge.get("recharge_location") or "detail page structured evidence"),
                        expires_rule=str(recharge.get("expiresRule") or recharge.get("expires_rule") or "Expiry not stated"),
                        verified=True,
                        confidence=confidence,
                        source=source,
                        evidence_url=evidence_url,
                        participates_in_verified_ranking=True,
                        notes="; ".join(tier_note_parts),
                    )
                )
    return tiers


def detail_record_verification_needed(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return "group_multiplier + recharge_tiers"
    missing: list[str] = []
    groups = record.get("groupMultipliers")
    recharges = record.get("rechargeTiers")
    if not isinstance(groups, list) or not groups:
        missing.append("group_multiplier")
    if not isinstance(recharges, list) or not recharges:
        missing.append("recharge_tiers")
    return " + ".join(missing)


def all_fee_rows(stations: dict[str, StationConfig]) -> list[FeeTier]:
    tiers = (
        nexus_verified_tiers()
        + live_probe_tiers()
        + detail_record_tiers(stations)
        + load_verified_input_tiers(stations)
        + public_discovered_tiers(stations)
        + known_public_shop_tiers(stations)
        + special_verified_tiers(stations)
        + freemodel_verified_tiers(stations)
    )
    return apply_station_pricing_overrides_to_tiers(tiers)


def load_station_pricing_overrides() -> dict[str, dict[str, Any]]:
    if not STATION_PRICING_OVERRIDES_PATH.exists():
        return {}
    try:
        payload = json.loads(STATION_PRICING_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(station).strip(): override
        for station, override in payload.items()
        if str(station).strip() and isinstance(override, dict)
    }


def apply_station_pricing_overrides_to_tiers(tiers: list[FeeTier]) -> list[FeeTier]:
    overrides = load_station_pricing_overrides()
    if not overrides:
        return tiers

    output: list[FeeTier] = []
    for tier in tiers:
        override = overrides.get(tier.station)
        if override and parse_bool(override.get("authoritative"), default=False):
            continue
        output.append(tier)

    for station, override in overrides.items():
        if not parse_bool(override.get("authoritative"), default=False):
            continue
        recharge_mode = override.get("rechargeMode")
        explicit_recharge_rows = [
            recharge
            for recharge in override.get("rechargeTiers", [])
            if isinstance(recharge, dict)
            and str(recharge.get("rechargeName") or recharge.get("recharge_name") or "").strip()
            and parse_float(recharge.get("rmbAmount") or recharge.get("rmb_amount")) is not None
            and parse_float(recharge.get("usdAmount") or recharge.get("usd_amount")) is not None
        ]
        if not explicit_recharge_rows and recharge_mode not in {
            "linear_rmb_to_usd",
            "sample_amount_to_usd_with_response_rmb",
            "sample_payment_amount_to_usd_1to1",
        }:
            continue
        usd_per_rmb = parse_float(override.get("usdPerRmb")) if recharge_mode == "linear_rmb_to_usd" else None
        usd_per_sample_unit = (
            parse_float(override.get("usdPerSampleUnit"))
            if recharge_mode == "sample_amount_to_usd_with_response_rmb"
            else None
        )
        usd_per_payment_unit = None
        if recharge_mode == "sample_payment_amount_to_usd_1to1":
            usd_per_payment_unit = parse_float(override.get("usdPerPaymentUnit")) or 1.0
        sample_payment_amount = (
            parse_float(override.get("samplePaymentAmount"))
            if recharge_mode == "sample_payment_amount_to_usd_1to1"
            else None
        )
        if not explicit_recharge_rows and recharge_mode == "linear_rmb_to_usd" and (not usd_per_rmb or usd_per_rmb <= 0):
            continue
        if not explicit_recharge_rows and recharge_mode == "sample_amount_to_usd_with_response_rmb" and (
            not usd_per_sample_unit or usd_per_sample_unit <= 0
        ):
            continue
        if not explicit_recharge_rows and recharge_mode == "sample_payment_amount_to_usd_1to1" and (
            not usd_per_payment_unit or usd_per_payment_unit <= 0
        ):
            continue
        pattern = re.compile(str(override.get("rechargeNamePattern") or r"wallet topup (\d+(?:\.\d+)?) RMB"), re.IGNORECASE)
        name_template = str(override.get("rechargeNameTemplate") or "wallet topup sample {rmb} RMB")
        recharge_location = str(override.get("rechargeLocation") or "").strip()
        expires_rule = str(override.get("expiresRule") or "").strip()
        participates_in_verified_ranking = parse_bool(
            override.get("participatesInVerifiedRanking"),
            default=True,
        )
        group_rows = [
            group
            for group in override.get("groupMultipliers", [])
            if isinstance(group, dict)
            and str(group.get("groupName") or group.get("group_name") or "").strip()
            and parse_float(group.get("groupMultiplier") or group.get("group_multiplier")) is not None
        ]
        source_tiers = []
        for tier in tiers:
            if tier.station != station or tier.rmb_amount is None:
                continue
            if pattern.search(tier.recharge_name) or sample_payment_amount is not None:
                source_tiers.append(tier)
        assumption = str(override.get("assumptionText") or "").strip()
        if explicit_recharge_rows:
            confidence = str(override.get("confidence") or "manual_verified").strip() or "manual_verified"
            source = str(override.get("source") or "station_pricing_override").strip() or "station_pricing_override"
            evidence_url = str(override.get("evidenceUrl") or override.get("evidence_url") or SITE_URL_OVERRIDES.get(station) or "").strip()
            recharge_location = str(override.get("rechargeLocation") or "").strip()
            expires_rule = str(override.get("expiresRule") or "").strip()
            participates_in_verified_ranking = parse_bool(
                override.get("participatesInVerifiedRanking"),
                default=True,
            )
            station_type = STATION_TYPE_OVERRIDES.get(station, "unknown_pending")
            label = station_display_label(station)
            seen_explicit: set[tuple[str, str, float | None, float | None]] = set()
            for recharge in explicit_recharge_rows:
                recharge_name = str(recharge.get("rechargeName") or recharge.get("recharge_name") or "").strip()
                billing_type = str(recharge.get("billingType") or recharge.get("billing_type") or "unknown").strip() or "unknown"
                rmb_amount = parse_float(recharge.get("rmbAmount") or recharge.get("rmb_amount"))
                usd_amount = parse_float(recharge.get("usdAmount") or recharge.get("usd_amount"))
                if not recharge_name or rmb_amount is None or usd_amount is None or rmb_amount <= 0 or usd_amount <= 0:
                    continue
                for group in group_rows:
                    group_name = str(group.get("groupName") or group.get("group_name") or "").strip()
                    group_multiplier = parse_float(group.get("groupMultiplier") or group.get("group_multiplier"))
                    if not group_name or group_multiplier is None:
                        continue
                    codex_eligible = parse_optional_bool(
                        group.get("codexEligible") if "codexEligible" in group else group.get("codex_eligible")
                    )
                    usage_label = str(group.get("usageLabel") or group.get("usage_label") or "").strip()
                    note_parts = [assumption] if assumption else []
                    if codex_eligible is False:
                        note_parts.append("codexEligible=false")
                    elif codex_eligible is True:
                        note_parts.append("codexEligible=true")
                    if usage_label:
                        note_parts.append(f"usage={usage_label}")
                    key = (group_name, recharge_name, rmb_amount, usd_amount)
                    if key in seen_explicit:
                        continue
                    seen_explicit.add(key)
                    effective = group_multiplier * rmb_amount / usd_amount
                    output.append(
                        FeeTier(
                            station=station,
                            label=label,
                            station_type=station_type,
                            group_name=group_name,
                            group_multiplier=group_multiplier,
                            recharge_name=recharge_name,
                            billing_type=billing_type,
                            rmb_amount=rmb_amount,
                            usd_amount=usd_amount,
                            effective_multiplier=effective,
                            recharge_location=str(recharge.get("rechargeLocation") or recharge.get("recharge_location") or recharge_location or "browser verified wallet page"),
                            expires_rule=str(recharge.get("expiresRule") or recharge.get("expires_rule") or expires_rule or "Expiry not stated"),
                            verified=True,
                            confidence=confidence,
                            source=source,
                            evidence_url=evidence_url,
                            participates_in_verified_ranking=participates_in_verified_ranking,
                            notes="; ".join(note_parts),
                        )
                    )
            continue
        seen: set[tuple[str, str, float | None]] = set()
        for source_tier in source_tiers:
            for group in group_rows:
                group_name = str(group.get("groupName") or group.get("group_name") or "").strip()
                group_multiplier = parse_float(group.get("groupMultiplier") or group.get("group_multiplier"))
                if not group_name or group_multiplier is None:
                    continue
                codex_eligible = parse_optional_bool(
                    group.get("codexEligible") if "codexEligible" in group else group.get("codex_eligible")
                )
                usage_label = str(group.get("usageLabel") or group.get("usage_label") or "").strip()
                next_notes_parts = [assumption or source_tier.notes]
                if codex_eligible is False:
                    next_notes_parts.append("codexEligible=false")
                elif codex_eligible is True:
                    next_notes_parts.append("codexEligible=true")
                if usage_label:
                    next_notes_parts.append(f"usage={usage_label}")
                if recharge_mode == "linear_rmb_to_usd":
                    recharge_name = source_tier.recharge_name
                    rmb_amount = source_tier.rmb_amount
                    usd_amount = rmb_amount * usd_per_rmb if rmb_amount is not None and usd_per_rmb else None
                elif recharge_mode == "sample_amount_to_usd_with_response_rmb":
                    match = pattern.search(source_tier.recharge_name)
                    sample_amount = parse_float(match.group(1)) if match else parse_float(source_tier.rmb_amount)
                    rmb_amount = source_tier.usd_amount
                    usd_amount = sample_amount * usd_per_sample_unit if sample_amount is not None and usd_per_sample_unit else None
                    recharge_name = name_template.format(
                        rmb=format_plain_number(rmb_amount),
                        usd=format_plain_number(usd_amount),
                    )
                else:
                    match = pattern.search(source_tier.recharge_name)
                    payment_amount = sample_payment_amount
                    if payment_amount is None and match:
                        payment_amount = parse_float(match.group(1))
                    if payment_amount is None:
                        payment_amount = parse_float(source_tier.usd_amount) or parse_float(source_tier.rmb_amount)
                    rmb_amount = payment_amount
                    usd_amount = (
                        payment_amount * usd_per_payment_unit
                        if payment_amount is not None and usd_per_payment_unit
                        else None
                    )
                    recharge_name = name_template.format(
                        rmb=format_plain_number(rmb_amount),
                        usd=format_plain_number(usd_amount),
                    )
                if rmb_amount is None or usd_amount is None or rmb_amount <= 0 or usd_amount <= 0:
                    continue
                effective = group_multiplier * rmb_amount / usd_amount
                key = (group_name, recharge_name, rmb_amount)
                if key in seen:
                    continue
                seen.add(key)
                output.append(
                    replace(
                        source_tier,
                        group_name=group_name,
                        group_multiplier=group_multiplier,
                        recharge_name=recharge_name,
                        rmb_amount=rmb_amount,
                        usd_amount=usd_amount,
                        effective_multiplier=effective,
                        recharge_location=recharge_location or source_tier.recharge_location,
                        expires_rule=expires_rule or source_tier.expires_rule,
                        confidence="manual_verified",
                        source="station_pricing_override",
                        notes="; ".join(part for part in next_notes_parts if part),
                        participates_in_verified_ranking=participates_in_verified_ranking,
                    )
                )
    return output


def is_low_confidence(confidence: str) -> bool:
    return confidence.startswith("low_")


def suspicious_multiplier_reason(value: float | None) -> str:
    if value is None:
        return ""
    if value < LOW_MULTIPLIER_REVIEW_THRESHOLD:
        return f"effective multiplier < {LOW_MULTIPLIER_REVIEW_THRESHOLD:g}; verify package quota, plan scope multiplier, and recharge conversion"
    if value >= HIGH_MULTIPLIER_REVIEW_THRESHOLD:
        return f"effective multiplier >= {HIGH_MULTIPLIER_REVIEW_THRESHOLD:g}; verify group multiplier, recharge conversion, and whether this is a fixed package"
    return ""


def is_suspicious_effective_multiplier(value: float | None) -> bool:
    return bool(suspicious_multiplier_reason(value))


def high_effective_multiplier_allowed_stations() -> set[str]:
    return {
        station
        for station, override in load_station_pricing_overrides().items()
        if parse_bool(override.get("allowHighEffectiveMultiplier"), default=False)
    }


NON_CODEX_EXCLUDED_KEYWORDS = (
    "claude",
    "cc-",
    "anthropic",
    "kiro",
    "windsurf",
    "bedrock",
    "sonnet",
    "opus",
    "haiku",
    "madeinchina",
    "国产",
    "公益",
    "deepseek",
    "qwen",
    "glm",
    "kimi",
    "doubao",
    "minimax",
)


def is_codex_like_group_text(*parts: str) -> bool:
    normalized = " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())
    if not normalized:
        return False
    return not any(keyword in normalized for keyword in NON_CODEX_EXCLUDED_KEYWORDS)


def is_codex_like_group_name(group_name: str) -> bool:
    return is_codex_like_group_text(group_name)


def is_codex_like_fee_tier(tier: FeeTier) -> bool:
    if "codexeligible=false" in str(tier.notes or "").strip().lower():
        return False
    if "codexeligible=true" in str(tier.notes or "").strip().lower():
        return True
    return is_codex_like_group_text(tier.group_name, tier.notes)


def choose_codex_or_fallback_tier(candidates: list[FeeTier]) -> FeeTier | None:
    codex_like_candidates = [tier for tier in candidates if is_codex_like_fee_tier(tier)]
    if codex_like_candidates:
        return min(codex_like_candidates, key=lambda tier: tier.effective_multiplier or float("inf"))
    return None


def choose_verified_fee(
    tiers: list[FeeTier],
    *,
    allow_low_confidence: bool,
) -> dict[str, FeeTier]:
    eligible_by_station: dict[str, list[FeeTier]] = {}
    high_multiplier_allowed = high_effective_multiplier_allowed_stations()
    for tier in tiers:
        if not tier.participates_in_verified_ranking or not tier.verified:
            continue
        if not allow_low_confidence and is_low_confidence(tier.confidence):
            continue
        if tier.effective_multiplier is None or tier.effective_multiplier <= 0:
            continue
        if (
            not allow_low_confidence
            and tier.station not in high_multiplier_allowed
            and is_suspicious_effective_multiplier(tier.effective_multiplier)
        ):
            continue
        eligible_by_station.setdefault(tier.station, []).append(tier)
    chosen: dict[str, FeeTier] = {}
    for station, candidates in eligible_by_station.items():
        selected = choose_codex_or_fallback_tier(candidates)
        if selected is not None:
            chosen[station] = selected
    return chosen


def compute_ranking(
    metrics: dict[str, dict[str, Any]],
    chosen_fees: dict[str, FeeTier],
    basis: str,
    time_window: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for station, fee in chosen_fees.items():
        metric = metrics.get(station)
        if not metric or not metric.get("requests"):
            continue
        if fee.effective_multiplier is None:
            continue
        rows.append(
            {
                "ranking_basis": basis,
                "time_window": time_window,
                "time_window_label": time_window_cn(time_window),
                "station": station,
                "label": station_display_label(station, fee.label),
                "station_type": fee.station_type,
                "station_type_label": station_type_cn(fee.station_type),
                "adopted_tier": f"{fee.group_name} | {fee.recharge_name}",
                "billing_type": fee.billing_type,
                "billing_type_label": billing_type_cn(fee.billing_type),
                "multiplier_full_use_assumption": expires_rule_cn(fee.expires_rule),
                "effective_multiplier": fee.effective_multiplier,
                "fee_verified": fee.verified,
                "fee_confidence": fee.confidence,
                "fee_confidence_label": confidence_cn(fee.confidence),
                "requests": metric["requests"],
                "correct": metric["correct"],
                "failures": metric["failures"],
                "http_2xx": metric["http_2xx"],
                "http_200_with_error": metric["http_200_with_error"],
                "correct_rate": metric["correct_rate"],
                "avg_ms": metric["avg_ms"],
                "median_ms": metric["median_ms"],
                "p95_ms": metric["p95_ms"],
                "avg_seconds": ms_to_seconds(metric["avg_ms"]),
                "median_seconds": ms_to_seconds(metric["median_ms"]),
                "p95_seconds": ms_to_seconds(metric["p95_ms"]),
                "first_at": metric["first_at"],
                "last_at": metric["last_at"],
            }
        )
    if not rows:
        return rows

    valid_latencies = [row["avg_ms"] for row in rows if row["avg_ms"] is not None]
    valid_fees = [row["effective_multiplier"] for row in rows if row["effective_multiplier"] is not None]
    lat_min = min(valid_latencies) if valid_latencies else 0
    lat_max = max(valid_latencies) if valid_latencies else 0
    fee_min = min(valid_fees) if valid_fees else 0
    fee_max = max(valid_fees) if valid_fees else 0

    for row in rows:
        success_score = (row["correct_rate"] or 0) * 100
        if row["avg_ms"] is None or not valid_latencies:
            latency_score = 0
        elif lat_max == lat_min:
            latency_score = 100
        else:
            latency_score = (lat_max - row["avg_ms"]) / (lat_max - lat_min) * 100
        if fee_max == fee_min:
            cost_score = 100
        else:
            cost_score = (fee_max - row["effective_multiplier"]) / (fee_max - fee_min) * 100
        row["success_score"] = success_score
        row["latency_score"] = latency_score
        row["cost_score"] = cost_score
        row["total_score"] = success_score * 0.40 + latency_score * 0.35 + cost_score * 0.25

    rows.sort(key=lambda row: (-row["total_score"], -row["requests"], row["station"]))
    for index, row in enumerate(rows, 1):
        row["rank"] = index
    return rows


def fee_tier_to_row(tier: FeeTier) -> dict[str, Any]:
    return {
        "station": tier.station,
        "label": station_display_label(tier.station, tier.label),
        "station_type": tier.station_type,
        "group_name": tier.group_name,
        "group_multiplier": tier.group_multiplier,
        "recharge_name": tier.recharge_name,
        "billing_type": tier.billing_type,
        "rmb_amount": tier.rmb_amount,
        "usd_amount": tier.usd_amount,
        "effective_multiplier": tier.effective_multiplier,
        "recharge_location": tier.recharge_location,
        "expires_rule": expires_rule_cn(tier.expires_rule),
        "verified": tier.verified,
        "confidence": tier.confidence,
        "source": tier.source,
        "evidence_url": tier.evidence_url,
        "participates_in_verified_ranking": tier.participates_in_verified_ranking,
        "notes": tier.notes,
    }


def public_fee_row(tier: FeeTier, stations: dict[str, StationConfig]) -> dict[str, Any]:
    station = stations.get(tier.station, StationConfig(tier.station, tier.label))
    row = fee_tier_to_row(tier)
    row["label"] = station_display_label(tier.station, row.get("label"))
    row["platform_guess"] = station.platform_guess
    return row


def high_multiplier_review_rows(
    rankings_by_window: dict[str, list[dict[str, Any]]],
    chosen_fees: dict[str, FeeTier],
    stations: dict[str, StationConfig],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    allowed_high_multiplier = high_effective_multiplier_allowed_stations()
    for window_name, ranking_rows in rankings_by_window.items():
        for ranking in ranking_rows:
            effective = parse_float(ranking.get("effective_multiplier"))
            if effective is None or effective < HIGH_MULTIPLIER_REVIEW_THRESHOLD:
                continue
            station_key = str(ranking.get("station") or "").strip()
            if station_key in allowed_high_multiplier:
                continue
            key = (station_key, window_name)
            if key in seen:
                continue
            seen.add(key)
            fee = chosen_fees.get(station_key)
            station = stations.get(station_key, StationConfig(station_key, station_display_label(station_key, ranking.get("label"))))
            rows.append(
                {
                    "station": station_key,
                    "label": station_display_label(station_key, ranking.get("label") or station.label),
                    "time_window": window_name,
                    "effective_multiplier": effective,
                    "adopted_tier": ranking.get("adopted_tier", ""),
                    "group_name": fee.group_name if fee else "",
                    "group_multiplier": fee.group_multiplier if fee else "",
                    "recharge_name": fee.recharge_name if fee else "",
                    "rmb_amount": fee.rmb_amount if fee else "",
                    "usd_amount": fee.usd_amount if fee else "",
                    "recharge_location": fee.recharge_location if fee else "",
                    "confidence": fee.confidence if fee else ranking.get("fee_confidence", ""),
                    "evidence_url": fee.evidence_url if fee else "",
                    "review_reason": f"adopted effective multiplier >= {HIGH_MULTIPLIER_REVIEW_THRESHOLD:g}; verify group multiplier, recharge conversion, billing validity, and evidence source",
                }
            )
    return sorted(rows, key=lambda row: (-float(row["effective_multiplier"]), row["station"], row["time_window"]))


def multiplier_sanity_review_rows(tiers: list[FeeTier]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for tier in tiers:
        if not tier.verified or not tier.participates_in_verified_ranking:
            continue
        reason = suspicious_multiplier_reason(tier.effective_multiplier)
        if not reason:
            continue
        key = (
            tier.station,
            tier.group_name,
            tier.recharge_name,
            tier.rmb_amount,
            tier.usd_amount,
            tier.effective_multiplier,
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "station": tier.station,
                "label": station_display_label(tier.station, tier.label),
                "effective_multiplier": tier.effective_multiplier,
                "group_name": tier.group_name,
                "group_multiplier": tier.group_multiplier,
                "recharge_name": tier.recharge_name,
                "billing_type": tier.billing_type,
                "rmb_amount": tier.rmb_amount,
                "usd_amount": tier.usd_amount,
                "recharge_location": tier.recharge_location,
                "confidence": tier.confidence,
                "source": tier.source,
                "participates_in_verified_ranking": tier.participates_in_verified_ranking,
                "evidence_url": tier.evidence_url,
                "review_reason": reason,
                "notes": tier.notes,
            }
        )
    return sorted(rows, key=lambda row: (row["station"], float(row["effective_multiplier"])))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def fmt_float(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def fmt_effective_multiplier(value: float | None) -> str:
    return "-" if value is None else f"{value:.6g}"


def escape_markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def station_type_cn(value: str) -> str:
    return STATION_TYPE_LABELS_CN.get(value, value)


def billing_type_cn(value: str) -> str:
    return BILLING_TYPE_LABELS_CN.get(value, value)


def confidence_cn(value: str) -> str:
    return CONFIDENCE_LABELS_CN.get(value, value)


def time_window_cn(value: str) -> str:
    return TIME_WINDOW_LABELS.get(value, value)


def expires_rule_cn(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    exact_map = {
        "100 USD/day; expires daily; 30-day full-use assumption": "按 30 天满额使用折算；每日 100 美元额度；当日未用完失效",
        "200 USD/day; expires daily; 30-day full-use assumption": "按 30 天满额使用折算；每日 200 美元额度；当日未用完失效",
        "400 USD/day; expires daily; 30-day full-use assumption": "按 30 天满额使用折算；每日 400 美元额度；当日未用完失效",
        "100 USD/day; expires the same day": "每日 100 美元额度；当天未用完失效",
        "Permanent quota; user says it does not expire": "永久额度；用户说明不过期",
        "No expiry stated; balance top-up": "未注明有效期；余额充值",
        "No expiry stated in wallet API response": "钱包接口未注明有效期",
        "Permanent quota; shop says 余额不限时": "永久额度；商店页写明余额不限时",
        "Permanent quota; shop says 冲多少用多少": "永久额度；商店页写明冲多少用多少",
        "Card-style recharge; no expiry stated on the shop page": "卡密式充值；商店页未注明有效期",
        "1:1 USD recharge; min 10 RMB per public pricing page": "公开价格页显示 1 人民币充 1 美元额度；最低充值 10 元",
        "Recharge min 10 RMB; expiry not stated publicly": "公开信息显示最低充值 10 元；未注明有效期",
        "Expiry not stated publicly": "公开信息未注明有效期",
        "Expiry not stated publicly; direct recharge page requires auth context": "公开信息未注明有效期；直充页面需要登录态",
        "1 month; total quota 480 USD per public announcement": "公开公告显示 1 个月总额度 480 美元",
        "1 month; total quota 240 USD per public announcement": "公开公告显示 1 个月总额度 240 美元",
        "7 days; total quota 120 USD per public announcement": "公开公告显示 7 天总额度 120 美元",
        "1 day; total quota 20 USD per public announcement": "公开公告显示 1 天总额度 20 美元",
    }
    if text in exact_map:
        return exact_map[text]
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return text
    translated = text
    replacements = [
        ("Subscription package", "订阅套餐"),
        ("1 month subscription", "1 个月订阅"),
        ("7 day subscription", "7 天订阅"),
        ("1 day subscription", "1 天订阅"),
        ("365 day package", "365 天套餐"),
        ("3 day package", "3 天套餐"),
        ("; quota resets daily", "；额度按天重置"),
        ("; quota resets weekly", "；额度按周重置"),
        ("; quota resets monthly", "；额度按月重置"),
        ("; total quota pool, no periodic reset", "；总额度池；不按周期重置"),
    ]
    for src, dst in replacements:
        translated = translated.replace(src, dst)
    return translated


def ms_to_seconds(value: float | None) -> float | None:
    return None if value is None else value / 1000.0


def fmt_seconds(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def has_formal_confidence(confidence: str) -> bool:
    return not is_low_confidence(confidence) and confidence != "needs_manual_review"


def resolved_station_type(
    station_key: str,
    stations: dict[str, StationConfig],
    tiers: list[FeeTier],
) -> str:
    fallback = stations.get(station_key, StationConfig(station_key, station_key)).station_type
    station_rows = [tier for tier in tiers if tier.station == station_key and tier.verified]
    explicit_row_types = {
        tier.station_type
        for tier in station_rows
        if tier.station_type in STATION_TYPE_LABELS and tier.station_type != "unknown_pending"
    }
    if "mixed" in explicit_row_types:
        return "mixed"
    billing_types = {tier.billing_type for tier in station_rows}
    has_subscription = any(billing_type in PACKAGE_BILLING_TYPES for billing_type in billing_types)
    has_non_subscription = any(billing_type not in PACKAGE_BILLING_TYPES for billing_type in billing_types)
    if has_subscription and has_non_subscription:
        return "mixed"
    if fallback == "mixed" and station_rows:
        return "mixed"
    if has_subscription:
        return "subscription"
    if has_non_subscription:
        return "non_subscription"
    return fallback if fallback in STATION_TYPE_LABELS else "unknown_pending"


def normalize_station_types(stations: dict[str, StationConfig], tiers: list[FeeTier]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for station_key in stations:
        resolved[station_key] = resolved_station_type(station_key, stations, tiers)
        stations[station_key].station_type = resolved[station_key]
    for tier in tiers:
        if tier.station in resolved:
            tier.station_type = resolved[tier.station]
    return resolved


def station_url_summary(station: StationConfig) -> str:
    return escape_markdown_cell(station_primary_url(station))


def station_primary_url(station: StationConfig) -> str:
    preferred = SITE_URL_OVERRIDES.get(station.key)
    if preferred:
        return preferred
    urls = sorted(station.configured_urls)
    return urls[0] if urls else "-"


def verification_instructions(platform: str) -> str:
    if platform in {"new-api", "new-api-like"}:
        return (
            "登录后打开 API Key/令牌创建页，记录全部分组名称与倍率；再打开钱包/充值页，"
            "如果跳转站外支付，继续跟到最终支付页，记录实付人民币、到账美元额度、赠送、有效期和手续费。"
        )
    if platform == "sub2api":
        return (
            "登录后查看 API Key 分组倍率，再查看充值页或订阅页，记录人民币到美元额度换算、"
            "月卡/周卡/日卡规则、有效期和是否用不完清零。"
        )
    return (
        "登录或查看公开文档，补齐 API Key 分组倍率，以及站内或站外全部充值档位、"
        "有效期、赠送和手续费规则。"
    )


def ranking_markdown_section(title: str, rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    lines.append(f"## {title}")
    lines.append("")
    if rows:
        lines.append("| 排名 | 站点 | 网址 | 类型 | 总分 | 正确响应率 | 平均响应时间（秒） | 采用倍率 | 采用倍率档位 | 倍率口径 | 请求样本数 |")
        lines.append("|---:|---|---|---|---:|---:|---:|---:|---|---|---:|")
        for row in rows:
            base = (
                f"| {row['rank']} | {row['label']} | {escape_markdown_cell(row['station_url'])} | {row['station_type_label']} | "
                f"{row['total_score']:.2f} | {fmt_pct(row['correct_rate'])} | "
                f"{fmt_seconds(row['avg_seconds'])} | {fmt_effective_multiplier(row['effective_multiplier'])} | "
                f"{escape_markdown_cell(row['adopted_tier'])} | {escape_markdown_cell(row['multiplier_full_use_assumption'])} |"
            )
            lines.append(f"{base} {row['requests']} |")
    else:
        lines.append("当前没有同时具备费用证据和请求样本的站点。")
    lines.append("")
    return lines


def summarize_station_tiers(station_key: str, tiers: list[FeeTier]) -> tuple[str, str]:
    station_rows = [tier for tier in tiers if tier.station == station_key and tier.verified]
    if not station_rows:
        return ("-", "-")
    lowest_tier = min(
        [tier for tier in station_rows if tier.effective_multiplier and tier.effective_multiplier > 0],
        key=lambda tier: tier.effective_multiplier or float("inf"),
        default=None,
    )
    if lowest_tier is None:
        adopted = "-"
    else:
        adopted = f"{lowest_tier.group_name} | {lowest_tier.recharge_name} | {fmt_effective_multiplier(lowest_tier.effective_multiplier)}"
    confs = sorted({confidence_cn(tier.confidence) for tier in station_rows})
    return adopted, "、".join(confs) if confs else "-"


def station_group_summary(station_key: str, tiers: list[FeeTier]) -> str:
    seen: set[tuple[str, float | None]] = set()
    items: list[str] = []
    for tier in sorted(
        [tier for tier in tiers if tier.station == station_key and tier.verified],
        key=lambda tier: (tier.group_name.lower(), tier.group_multiplier if tier.group_multiplier is not None else float("inf")),
    ):
        marker = (tier.group_name, tier.group_multiplier)
        if marker in seen:
            continue
        seen.add(marker)
        items.append(f"{tier.group_name} ×{fmt_effective_multiplier(tier.group_multiplier)}")
    return "<br>".join(escape_markdown_cell(item) for item in items) if items else "待补证据"


def station_recharge_summary(station_key: str, tiers: list[FeeTier]) -> str:
    seen: set[tuple[Any, ...]] = set()
    items: list[str] = []
    for tier in sorted(
        [tier for tier in tiers if tier.station == station_key and tier.verified],
        key=lambda tier: (
            tier.billing_type,
            tier.rmb_amount if tier.rmb_amount is not None else float("inf"),
            tier.usd_amount if tier.usd_amount is not None else float("inf"),
            tier.recharge_name.lower(),
        ),
    ):
        marker = (
            tier.recharge_name,
            tier.billing_type,
            tier.rmb_amount,
            tier.usd_amount,
            tier.recharge_location,
            tier.expires_rule,
        )
        if marker in seen:
            continue
        seen.add(marker)
        if tier.recharge_name == "__group_only__":
            continue
        if tier.rmb_amount is not None and tier.usd_amount is not None:
            price_text = f"¥{fmt_float(tier.rmb_amount, 2)} -> ${fmt_float(tier.usd_amount, 2)}"
        elif tier.rmb_amount is not None:
            price_text = f"¥{fmt_float(tier.rmb_amount, 2)}；到账美元额度待补证据"
        elif tier.usd_amount is not None:
            price_text = f"到账 ${fmt_float(tier.usd_amount, 2)}；人民币支付金额待补证据"
        else:
            price_text = "金额与到账额度待补证据"
        items.append(f"{tier.recharge_name}（{billing_type_cn(tier.billing_type)}，{price_text}）")
    return "<br>".join(escape_markdown_cell(item) for item in items) if items else "待补证据"


def write_markdown(
    path: Path,
    stations: dict[str, StationConfig],
    primary_metrics: dict[str, dict[str, Any]],
    tiers: list[FeeTier],
    formal_work_ranking: list[dict[str, Any]],
    formal_off_ranking: list[dict[str, Any]],
) -> None:
    verified_count = sum(1 for tier in tiers if tier.verified)
    high_confidence_count = sum(1 for tier in tiers if tier.verified and has_formal_confidence(tier.confidence))
    fully_verified_stations = {
        tier.station for tier in tiers if tier.verified and has_formal_confidence(tier.confidence)
    }
    formal_ranked_stations = {row["station"] for row in formal_work_ranking} | {row["station"] for row in formal_off_ranking}
    pending_stations = [key for key in sorted(stations) if key not in fully_verified_stations]
    unrated_stations = [key for key in sorted(stations) if key not in formal_ranked_stations]
    formal_fee_map = choose_verified_fee(tiers, allow_low_confidence=False)

    lines: list[str] = []
    lines.append("# 中转站倍率核验与综合排名")
    lines.append("")
    lines.append(f"- 采集时间：{GENERATED_AT}")
    lines.append("- Codex Manager 数据库：本机只读 request log 数据库（路径不写入公开摘要）。")
    lines.append("- 正确响应定义：HTTP 2xx 且 `error IS NULL`。HTTP 200 但 `error` 非空也计为错误响应；因欠费、充值解锁、手机号验证等账户前置条件导致的错误样本，已从正确响应率统计中剔除。")
    lines.append("- 工作时段：周一至周五 09:00:00-18:00:00。")
    lines.append("- 非工作时段：工作日 18:00:01-次日 08:59:59，且周末全天计入非工作时段。")
    lines.append(f"- 主排名采用：{time_window_cn(PRIMARY_TIME_WINDOW)} 的请求日志。")
    lines.append("- 正式排名只使用高置信度或人工核验费用证据；截图中的倍率已忽略；0 倍率分组不参与排名。")
    lines.append("- 采用倍率计算公式：实际倍率 = 分组倍率 × 实付人民币 ÷ 到账美元额度。")
    lines.append("- 正式采用倍率 = 该站点所有已核验、非 0、可参与排名档位中的最低实际倍率。")
    lines.append("- 综合评分权重：正确响应率 40% + 响应时间 35% + 实际倍率 25%。")
    lines.append("- 环境说明：本次数据来自本机 Codex Manager 对多家中转站 Codex API Key 的聚合调用日志。费用口径统一按各站当前可核验的最低倍率档位计算，这通常也是最便宜、但往往延迟更高且更不稳定的一档。由于所有请求都先经过 Codex Manager 再转发给各中转站，因此相较直连会天然增加一层延迟。日志样本来自实际开发 1 到 2 个小项目期间的调用记录，网络环境为昆明广电宽带。以下排名仅基于 2026-05-15 当天、当前账号状态与当前网络环境的观测结果，无任何利益相关，仅供参考。")
    lines.append("")
    lines.extend(ranking_markdown_section("正式综合排名（工作时段）", formal_work_ranking))
    lines.extend(ranking_markdown_section("正式综合排名（非工作时段）", formal_off_ranking))
    lines.append("## 未进入正式排名的站点池")
    lines.append("")
    lines.append("| 站点 | 网址 | 平台判断 | 工作时段样本数 | 未进入正式排名原因 |")
    lines.append("|---|---|---|---:|---|")
    for key in unrated_stations:
        station = stations[key]
        metric = primary_metrics.get(key, {})
        reasons: list[str] = []
        if key not in formal_fee_map:
            reasons.append("缺少可参与正式排名的高置信度非 0 费用证据")
        if not metric.get("requests"):
            reasons.append("工作时段没有请求样本")
        if not reasons:
            reasons.append("已进入正式排名")
        lines.append(
            f"| {station.label} | {station_url_summary(station)} | {station.platform_guess} | "
            f"{metric.get('requests', 0)} | {escape_markdown_cell('；'.join(reasons))} |"
        )
    lines.append("")
    lines.append("## 成本分类快照")
    lines.append("")
    monthly_tiers = [t for t in tiers if t.verified and t.billing_type in PACKAGE_BILLING_TYPES]
    payg_tiers = [t for t in tiers if t.verified and t.billing_type == "permanent"]
    mixed_stations = sorted({t.label for t in tiers if t.verified and t.station_type == "mixed"})
    low_confidence_rows = [t for t in tiers if t.verified and is_low_confidence(t.confidence)]
    formal_stations = sorted({row["label"] for row in formal_work_ranking})
    lines.append(f"- 已核验套餐/满额使用档位数：{len(monthly_tiers)}")
    lines.append(f"- 已核验永久额度/按量充值档位数：{len(payg_tiers)}")
    lines.append(f"- 已核验混合型站点：{'、'.join(mixed_stations) if mixed_stations else '-'}")
    lines.append(f"- 高置信度已核验档位数：{high_confidence_count}")
    lines.append(f"- 低置信度公开证据档位数：{len(low_confidence_rows)}")
    lines.append(f"- 已进入正式工作时段排名的站点：{'、'.join(formal_stations) if formal_stations else '-'}")
    lines.append("")
    lines.append("## 全部档位倍率表")
    lines.append("")
    lines.append("| 站点 | 网址 | 站点类型 | 所有分组倍率 | 所有充值档位 |")
    lines.append("|---|---|---|---|---|")
    for station_key in sorted(stations, key=lambda key: stations[key].label.lower()):
        station = stations[station_key]
        lines.append(
            f"| {station.label} | {station_url_summary(station)} | {station_type_cn(station.station_type)} | "
            f"{station_group_summary(station_key, tiers)} | {station_recharge_summary(station_key, tiers)} |"
        )
    lines.append("")
    lines.append("## 各站点档位汇总")
    lines.append("")
    lines.append("| 站点 | 网址 | 站点类型 | 已核验档位数 | 最低非 0 倍率档位 | 工作时段样本数 | 工作时段正确率 | 工作时段平均响应时间（秒） |")
    lines.append("|---|---|---|---:|---|---:|---:|---:|")
    for station_key in sorted(stations, key=lambda key: stations[key].label.lower()):
        station = stations[station_key]
        tier_count = sum(1 for tier in tiers if tier.station == station_key and tier.verified)
        adopted, _conf_text = summarize_station_tiers(station_key, tiers)
        metric = primary_metrics.get(station_key, {})
        lines.append(
            f"| {station.label} | {station_url_summary(station)} | {station_type_cn(station.station_type)} | {tier_count} | "
            f"{escape_markdown_cell(adopted)} | {metric.get('requests', 0)} | "
            f"{fmt_pct(metric.get('correct_rate'))} | {fmt_seconds(ms_to_seconds(metric.get('avg_ms')))} |"
        )
    lines.append("")
    lines.append("## 待补证据")
    lines.append("")
    lines.append(f"- 已写入的核验档位总数：{verified_count}")
    lines.append(f"- 仍需登录页核验或补齐证据的站点数：{len(pending_stations)}")
    lines.append("- 充值页可能在站内，也可能跳转到站外；采集时要同时记录入口 URL 和最终支付 URL。")
    lines.append("")
    lines.append("| 站点 | 平台判断 | URL | 工作时段样本数 | 未补齐原因 | 仍需补充的证据 |")
    lines.append("|---|---|---|---:|---|---|")
    for key in pending_stations:
        station = stations[key]
        metric = primary_metrics.get(key, {})
        highest_confidence = sorted({tier.confidence for tier in tiers if tier.station == key and tier.verified})
        if not highest_confidence:
            reason = "缺少费用证据"
        elif all(is_low_confidence(conf) for conf in highest_confidence):
            reason = "只有低置信公开证据，需登录后复核"
        else:
            reason = "已具备正式可用证据"
        if not metric.get("requests"):
            reason = f"{reason}；工作时段无请求样本" if reason else "工作时段无请求样本"
        needed = "API Key 分组倍率 + 所有充值档位"
        if key not in formal_fee_map:
            needed += "；需要高置信度或人工核验"
        lines.append(
            f"| {station.label} | {station.platform_guess} | {station_url_summary(station)} | "
            f"{metric.get('requests', 0)} | {escape_markdown_cell(reason)} | {needed} |"
        )
    lines.append("")
    lines.append("## 需要你协助登录的站点")
    lines.append("")
    login_needed = [key for key in pending_stations if key not in formal_fee_map or not primary_metrics.get(key, {}).get("requests")]
    if login_needed:
        lines.append(f"- 请一次性在 Tabbit 打开：{'、'.join(stations[key].label for key in sorted(login_needed))}")
        for key in sorted(login_needed):
            station = stations[key]
            if key == "freemodel":
                lines.append(
                    f"- {station.label}：已确认订阅结构和 Stripe 计费框架，但还缺“实际付款币种/人民币折算”证据。请打开 `账单` 或 `立即充值` 后的结算页，记录订阅价格、额外充值价格、支付币种、是否可直接人民币付款。"
                )
            elif key == "voapi":
                lines.append(
                    f"- {station.label}：已确认钱包页显示 `$10 -> $10 USD`，但尚未确认人民币支付口径。请在钱包页尝试切换支付币种/支付方式，记录是否支持人民币、实际支付金额、到账金额、以及 API 令牌页可见的分组倍率。"
                )
            elif key == "muskai":
                lines.append(
                    f"- {station.label}：已拿到分组倍率和登录态外链支付页入口，但还缺支付商品明细。请在 `充值` 或 `我的订阅` 页把套餐卡片完整打开，记录每个档位的人民币价格、到账额度、有效期、是否当日/当期清零。"
                )
            elif key == "loomex":
                lines.append(
                    f"- {station.label}：当前停在登录页。请先完成登录，随后需要补 `API Key/令牌创建页` 的全部分组倍率，以及 `钱包/充值页` 的全部充值档位和最终支付地址。"
                )
            else:
                lines.append(
                    f"- {station.label}：登录后优先补 `API Key 分组倍率`、`全部充值档位`、`站内/站外最终充值 URL`、`人民币到美元额度换算`。"
                )
    else:
        lines.append("- 当前没有必须补登录的站点。")
    lines.append("")
    lines.append("## 登录核验路线")
    lines.append("")
    lines.append("- `New API / New-API-like`：先看 API Key/令牌创建页的分组倍率，再看钱包/充值页，必要时继续跟到站外支付页。")
    lines.append("- `sub2api`：先看 API Key 分组倍率，再看充值页或订阅页，记录月卡/周卡/日卡规则和有效期。")
    lines.append("- `special`：手工采集同样信息，并记录是否跳转到站外支付。")
    lines.append("- 补完证据后，把数据写入 `verified_multiplier_inputs.csv` 或直接改脚本逻辑，再重新运行。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh Codex Manager request log quality metrics and ranking CSVs.",
        epilog=(
            "Every run also writes request_log_station_candidates.csv for newly discovered public hosts "
            f"and multiplier_sanity_review.csv for effective multipliers < {LOW_MULTIPLIER_REVIEW_THRESHOLD:g} "
            f"or >= {HIGH_MULTIPLIER_REVIEW_THRESHOLD:g} that need verification."
        ),
    )
    parser.add_argument(
        "--full-log-rebuild",
        action="store_true",
        help=(
            "Rebuild cumulative metrics from every /v1/responses request_log row in the DB. "
            "Only use this when historical Codex Manager logs are still complete; otherwise "
            "keep the default incremental mode backed by data/codex-log-refresh-state.json."
        ),
    )
    parser.add_argument(
        "--log-source",
        choices=("sqlite", "postgres"),
        default="sqlite",
        help="Read Codex request logs from the local Codex Manager SQLite DB or from PostgreSQL request_log_events.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stations = load_station_configs(log_source=args.log_source)
    metrics_by_window = load_request_metrics(full_log_rebuild=args.full_log_rebuild, log_source=args.log_source)
    ensure_metric_station_configs(stations, metrics_by_window)
    primary_metrics = metrics_by_window[PRIMARY_TIME_WINDOW]
    all_hour_metrics = metrics_by_window["all_hours"]
    off_hour_metrics = metrics_by_window["off_hours"]
    probes = enrich_platforms(stations)
    tiers = all_fee_rows(stations)
    normalize_station_types(stations, tiers)

    formal_fees = choose_verified_fee(tiers, allow_low_confidence=False)
    formal_ranking = compute_ranking(primary_metrics, formal_fees, "formal_high_confidence", PRIMARY_TIME_WINDOW)
    formal_all_ranking = compute_ranking(all_hour_metrics, formal_fees, "formal_high_confidence", "all_hours")
    formal_off_ranking = compute_ranking(off_hour_metrics, formal_fees, "formal_high_confidence", "off_hours")
    for ranking_rows in (formal_ranking, formal_all_ranking, formal_off_ranking):
        for row in ranking_rows:
            row["station_url"] = station_primary_url(stations[row["station"]])

    tier_fieldnames = [
        "station",
        "label",
        "station_type",
        "group_name",
        "group_multiplier",
        "recharge_name",
        "billing_type",
        "rmb_amount",
        "usd_amount",
        "effective_multiplier",
        "recharge_location",
        "expires_rule",
        "verified",
        "confidence",
        "source",
        "evidence_url",
        "participates_in_verified_ranking",
        "notes",
    ]
    write_csv(WORKSPACE / "multiplier_tiers.csv", [fee_tier_to_row(t) for t in tiers], tier_fieldnames)

    public_fee_rows = [
        public_fee_row(tier, stations)
        for tier in tiers
        if tier.verified and tier.confidence.startswith("low_")
    ]
    write_csv(
        PUBLIC_FEE_EVIDENCE_PATH,
        public_fee_rows,
        [
            "station",
            "label",
            "station_type",
            "platform_guess",
            "group_name",
            "group_multiplier",
            "recharge_name",
            "billing_type",
            "rmb_amount",
            "usd_amount",
            "effective_multiplier",
            "recharge_location",
            "expires_rule",
            "confidence",
            "source",
            "evidence_url",
            "participates_in_verified_ranking",
            "notes",
        ],
    )

    ranking_fieldnames = [
        "rank",
        "ranking_basis",
        "time_window",
        "time_window_label",
        "station",
        "label",
        "station_url",
        "station_type",
        "station_type_label",
        "total_score",
        "success_score",
        "latency_score",
        "cost_score",
        "correct_rate",
        "avg_seconds",
        "median_seconds",
        "p95_seconds",
        "effective_multiplier",
        "fee_verified",
        "adopted_tier",
        "billing_type",
        "billing_type_label",
        "multiplier_full_use_assumption",
        "requests",
        "correct",
        "failures",
        "http_2xx",
        "http_200_with_error",
        "first_at",
        "last_at",
    ]
    write_csv(WORKSPACE / "composite_ranking_verified.csv", formal_ranking, ranking_fieldnames)
    write_csv(WORKSPACE / "composite_ranking_formal.csv", formal_ranking, ranking_fieldnames)
    write_csv(WORKSPACE / "composite_ranking_formal_workhours.csv", formal_ranking, ranking_fieldnames)
    write_csv(WORKSPACE / "composite_ranking_formal_offhours.csv", formal_off_ranking, ranking_fieldnames)
    write_csv(WORKSPACE / "composite_ranking_formal_all_hours.csv", formal_all_ranking, ranking_fieldnames)
    sanity_rows = multiplier_sanity_review_rows(tiers)
    write_csv(
        MULTIPLIER_SANITY_REVIEW_PATH,
        sanity_rows,
        [
            "station",
            "label",
            "effective_multiplier",
            "group_name",
            "group_multiplier",
            "recharge_name",
            "billing_type",
            "rmb_amount",
            "usd_amount",
            "recharge_location",
            "confidence",
            "source",
            "participates_in_verified_ranking",
            "evidence_url",
            "review_reason",
            "notes",
        ],
    )
    high_multiplier_rows = high_multiplier_review_rows(
        {
            PRIMARY_TIME_WINDOW: formal_ranking,
            "off_hours": formal_off_ranking,
            "all_hours": formal_all_ranking,
        },
        formal_fees,
        stations,
    )
    write_csv(
        HIGH_MULTIPLIER_REVIEW_PATH,
        high_multiplier_rows,
        [
            "station",
            "label",
            "time_window",
            "effective_multiplier",
            "adopted_tier",
            "group_name",
            "group_multiplier",
            "recharge_name",
            "rmb_amount",
            "usd_amount",
            "recharge_location",
            "confidence",
            "evidence_url",
            "review_reason",
        ],
    )

    quality_rows: list[dict[str, Any]] = []
    for key in sorted(stations):
        station = stations[key]
        for window_name in (PRIMARY_TIME_WINDOW, "off_hours", "all_hours"):
            metric = metrics_by_window[window_name].get(key, {})
            quality_rows.append(
                {
                    "station": key,
                    "label": station_display_label(key, station.label),
                    "platform_guess": station.platform_guess,
                    "time_window": window_name,
                    "time_window_label": time_window_cn(window_name),
                    "request_samples": metric.get("requests", 0),
                    "correct": metric.get("correct", 0),
                    "failures": metric.get("failures", 0),
                    "correct_rate": metric.get("correct_rate"),
                    "http_2xx": metric.get("http_2xx", 0),
                    "http_200_with_error": metric.get("http_200_with_error", 0),
                    "nonnull_error": metric.get("nonnull_error", 0),
                    "excluded_billing_errors": metric.get("excluded_billing_errors", 0),
                    "avg_ms": metric.get("avg_ms"),
                    "median_ms": metric.get("median_ms"),
                    "p95_ms": metric.get("p95_ms"),
                    "avg_seconds": ms_to_seconds(metric.get("avg_ms")),
                    "median_seconds": ms_to_seconds(metric.get("median_ms")),
                    "p95_seconds": ms_to_seconds(metric.get("p95_ms")),
                    "avg_first_response_ms": metric.get("avg_first_response_ms"),
                    "avg_first_response_seconds": ms_to_seconds(metric.get("avg_first_response_ms")),
                    "first_at": metric.get("first_at", ""),
                    "last_at": metric.get("last_at", ""),
                    "configured_urls": "; ".join(sorted(station.configured_urls)),
                    "configured_suppliers": "; ".join(sorted(s for s in station.configured_suppliers if s)),
                }
            )
    write_csv(
        WORKSPACE / "quality_metrics.csv",
        quality_rows,
        [
            "station",
            "label",
            "platform_guess",
            "time_window",
            "time_window_label",
            "request_samples",
            "correct",
            "failures",
            "correct_rate",
            "http_2xx",
            "http_200_with_error",
            "nonnull_error",
            "excluded_billing_errors",
            "avg_seconds",
            "median_seconds",
            "p95_seconds",
            "avg_first_response_seconds",
            "first_at",
            "last_at",
            "configured_urls",
            "configured_suppliers",
        ],
    )

    checklist_rows: list[dict[str, Any]] = []
    station_confidences: dict[str, set[str]] = {}
    for tier in tiers:
        if tier.verified:
            station_confidences.setdefault(tier.station, set()).add(tier.confidence)
    fully_verified_stations = {
        station
        for station, confidences in station_confidences.items()
        if any(has_formal_confidence(confidence) for confidence in confidences)
    }
    site_detail_records = site_data_station_records()
    for key in sorted(stations):
        station = stations[key]
        metric = primary_metrics.get(key, {})
        probe = probes.get(key, {})
        detail_verification_needed = detail_record_verification_needed(site_detail_records.get(key))
        checklist_rows.append(
            {
                "station": key,
                "label": station_display_label(key, station.label),
                "station_type": station.station_type,
                "platform_guess": station.platform_guess,
                "urls": "; ".join(sorted(station.configured_urls)),
                "configured_suppliers": "; ".join(sorted(s for s in station.configured_suppliers if s)),
                "request_samples": metric.get("requests", 0),
                "verified_fee_available": key in station_confidences,
                "highest_fee_confidence": "; ".join(sorted(station_confidences.get(key, set()))),
                "probe_title": probe.get("title", ""),
                "probe_final_url": probe.get("final_url", ""),
                "probe_error": probe.get("error", ""),
                "verification_needed": ""
                if key in fully_verified_stations
                else detail_verification_needed
                if key not in station_confidences
                else "login-page cross-check for low-confidence public evidence",
                "recharge_location_to_record": "in-site entry and external final URL if redirected",
                "instructions": "" if key in fully_verified_stations or not detail_verification_needed else verification_instructions(station.platform_guess),
            }
        )
    write_csv(
        WORKSPACE / "login_verification_checklist.csv",
        checklist_rows,
        [
            "station",
            "label",
            "station_type",
            "platform_guess",
            "urls",
            "configured_suppliers",
            "request_samples",
            "verified_fee_available",
            "probe_title",
            "probe_final_url",
            "probe_error",
            "verification_needed",
            "recharge_location_to_record",
            "instructions",
        ],
    )

    probe_rows = []
    for key in sorted(stations):
        probe = probes.get(key, {})
        probe_rows.append(
            {
                "station": key,
                "label": station_display_label(key, stations[key].label),
                "url": probe.get("url", ""),
                "final_url": probe.get("final_url", ""),
                "http_status": probe.get("http_status", ""),
                "platform": probe.get("platform", ""),
                "title": probe.get("title", ""),
                "error": probe.get("error", ""),
            }
        )
    write_csv(
        WORKSPACE / "public_probe_results.csv",
        probe_rows,
        ["station", "label", "url", "final_url", "http_status", "platform", "title", "error"],
    )

    monthly_rows = [
        fee_tier_to_row(t)
        for t in sorted(
            [t for t in tiers if t.verified and t.billing_type in PACKAGE_BILLING_TYPES],
            key=lambda tier: tier.effective_multiplier or float("inf"),
        )
    ]
    payg_rows = [
        fee_tier_to_row(t)
        for t in sorted(
            [t for t in tiers if t.verified and t.billing_type == "permanent"],
            key=lambda tier: tier.effective_multiplier or float("inf"),
        )
    ]
    write_csv(WORKSPACE / "package_full_use_cost_ranking.csv", monthly_rows, tier_fieldnames)
    write_csv(WORKSPACE / "monthly_full_use_cost_ranking.csv", monthly_rows, tier_fieldnames)
    write_csv(WORKSPACE / "payg_cost_ranking.csv", payg_rows, tier_fieldnames)

    pending_rows = [row for row in checklist_rows if row["verification_needed"]]
    write_csv(
        WORKSPACE / "pending_evidence.csv",
        pending_rows,
        [
            "station",
            "label",
            "station_type",
            "platform_guess",
            "urls",
            "request_samples",
            "verified_fee_available",
            "probe_title",
            "probe_final_url",
            "probe_error",
            "verification_needed",
            "recharge_location_to_record",
            "instructions",
        ],
    )

    write_markdown(
        WORKSPACE / "multiplier_audit_summary.md",
        stations,
        primary_metrics,
        tiers,
        formal_ranking,
        formal_off_ranking,
    )

    obsolete_files = [
        WORKSPACE / "composite_ranking_provisional.csv",
        WORKSPACE / "composite_ranking_provisional_workhours.csv",
        WORKSPACE / "composite_ranking_provisional_offhours.csv",
        WORKSPACE / "composite_ranking_provisional_all_hours.csv",
    ]
    for obsolete_path in obsolete_files:
        if obsolete_path.exists():
            obsolete_path.unlink()

    print(
        json.dumps(
            {
                "generated_at": GENERATED_AT,
                "files": [
                    workspace_public_path(WORKSPACE / "multiplier_tiers.csv"),
                    workspace_public_path(PUBLIC_FEE_EVIDENCE_PATH),
                    workspace_public_path(REQUEST_LOG_STATION_CANDIDATES_PATH),
                    workspace_public_path(HIGH_MULTIPLIER_REVIEW_PATH),
                    workspace_public_path(MULTIPLIER_SANITY_REVIEW_PATH),
                    workspace_public_path(LOG_REFRESH_STATE_PATH),
                    workspace_public_path(WORKSPACE / "composite_ranking_verified.csv"),
                    workspace_public_path(WORKSPACE / "composite_ranking_formal.csv"),
                    workspace_public_path(WORKSPACE / "composite_ranking_formal_workhours.csv"),
                    workspace_public_path(WORKSPACE / "composite_ranking_formal_offhours.csv"),
                    workspace_public_path(WORKSPACE / "composite_ranking_formal_all_hours.csv"),
                    workspace_public_path(WORKSPACE / "quality_metrics.csv"),
                    workspace_public_path(WORKSPACE / "login_verification_checklist.csv"),
                    workspace_public_path(WORKSPACE / "public_probe_results.csv"),
                    workspace_public_path(WORKSPACE / "package_full_use_cost_ranking.csv"),
                    workspace_public_path(WORKSPACE / "monthly_full_use_cost_ranking.csv"),
                    workspace_public_path(WORKSPACE / "payg_cost_ranking.csv"),
                    workspace_public_path(WORKSPACE / "pending_evidence.csv"),
                    workspace_public_path(WORKSPACE / "multiplier_audit_summary.md"),
                ],
                "station_count": len(stations),
                "verified_tier_count": sum(1 for tier in tiers if tier.verified),
                "formal_ranked_count": len(formal_ranking),
                "formal_offhours_ranked_count": len(formal_off_ranking),
                "high_multiplier_review_count": len(high_multiplier_rows),
                "multiplier_sanity_review_count": len(sanity_rows),
                "stations_needing_login_evidence": len(pending_rows),
                "log_refresh": LAST_LOG_REFRESH_INFO,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
