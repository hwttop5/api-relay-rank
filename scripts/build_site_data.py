#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
SOURCE_ROOTS = [APP_ROOT, WORKSPACE_ROOT]
DATA_DIR = APP_ROOT / "data"
SITE_DATA_PATH = DATA_DIR / "site-data.json"
PUBLIC_FETCH_DIR = Path(os.environ.get("PUBLIC_FETCH_DIR", DATA_DIR / "_public_fetch"))
AUDIT_RUNS_DIR = DATA_DIR / "_audit_runs"
PUBLIC_FETCH_DIRS = [PUBLIC_FETCH_DIR]
STATION_PRICING_OVERRIDES_PATH = APP_ROOT / "config" / "station_pricing_overrides.json"
STATION_AUDIT_TARGETS_PATH = APP_ROOT / "config" / "station_audit_targets.json"

SHORT_TYPE_LABELS = {
    "subscription": "包月型",
    "non_subscription": "非包月型",
    "mixed": "混合型",
    "unknown_pending": "待补证据",
}

FULL_TYPE_LABELS = {
    "subscription": "包月型中转站",
    "non_subscription": "非包月型中转站",
    "mixed": "混合型中转站",
    "unknown_pending": "待补证据",
}

BILLING_LABELS = {
    "monthly": "月卡",
    "weekly": "周卡",
    "daily": "日卡",
    "permanent": "永久额度",
    "permanent_or_unknown": "按量额度",
}

TIME_WINDOWS = {
    "work_hours": {"key": "work_hours", "label": "工作时段", "range": "09:00:00-18:00:00"},
    "off_hours": {"key": "off_hours", "label": "非工作时段", "range": "18:00:01-次日08:59:59"},
    "all_hours": {"key": "all_hours", "label": "全时段", "range": "00:00:00-23:59:59"},
}

HIGHLIGHT_PHRASE = "所以本排名更关注各中转站的服务下限。"
DISCLAIMER_EMPHASIS = "本排名无任何利益相关，仅供参考。"
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
PATH_PATTERN = re.compile(r"([A-Za-z]:\\Users\\)([^\\`]+)")
TOPUP_NAME_PATTERN = re.compile(r"wallet topup (\d+(?:\.\d+)?) RMB", re.IGNORECASE)
TOPUP_HTML_PATTERN = re.compile(
    r"(wallet\s*topup\s*(\d+(?:\.\d+)?)\s*RMB).*?(\d+(?:\.\d+)?)\s*(?:USD|\$)",
    re.IGNORECASE | re.DOTALL,
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


def read_existing_site_data() -> dict[str, Any]:
    return json.loads(SITE_DATA_PATH.read_text(encoding="utf-8"))


def parse_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: Any) -> int:
    number = parse_float(value)
    return int(number or 0)


def parse_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def split_list(value: Any) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def sanitize_public_text(value: Any) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = PATH_PATTERN.sub(r"\1xxx", text)
    text = EMAIL_PATTERN.sub("xxx", text)
    text = re.sub(r"(?i)ttop5", "xxx", text)
    return text


def normalize_public_text(value: Any) -> str:
    text = sanitize_public_text(value)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 \2", text)
    return text


def station_url(value: Any) -> str:
    urls = split_list(value)
    return sanitize_public_text(urls[0]) if urls else ""


def choose_best_url(urls: list[str]) -> str:
    def score(url: str) -> tuple[int, int, str]:
        if not url:
            return (-10**6, 0, "")
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        base_score = 0
        if parsed.scheme == "https":
            base_score += 20
        if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+(?::\d+)?", host):
            base_score += 14
        else:
            base_score -= 12
        if host.startswith("api."):
            base_score -= 8
        if host.startswith("admin."):
            base_score -= 12
        if host.startswith("next."):
            base_score -= 3
        if host.count(".") <= 2:
            base_score += 4
        if parsed.port:
            base_score -= 2
        return (base_score, -len(host), url)

    candidates = [candidate for candidate in urls if candidate]
    if not candidates:
        return ""
    return max(candidates, key=score)


def format_plain_number(value: float | None) -> str:
    if value is None:
        return ""
    rounded = round(value, 10)
    if abs(rounded - int(rounded)) < 1e-10:
        return str(int(rounded))
    text = f"{rounded:.10f}".rstrip("0").rstrip(".")
    return text


def split_label_value(item: str) -> tuple[str, str]:
    for separator in ("：", ":"):
        if separator in item:
            left, right = item.split(separator, 1)
            return left.strip(), right.strip()
    return item.strip(), ""


def load_summary_intro() -> dict[str, Any]:
    summary_path = resolve_source_path("multiplier_audit_summary.md")
    generated_at = ""

    if summary_path and summary_path.exists():
        summary_text = summary_path.read_text(encoding="utf-8-sig")
        lines = summary_text.splitlines()

        bullet_items: list[str] = []
        for line in lines[1:]:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                bullet_items.append(sanitize_public_text(line[2:].strip()))

        for item in bullet_items:
            label, value = split_label_value(item)
            if label == "采集时间" and value:
                generated_at = value

    if not generated_at and SITE_DATA_PATH.exists():
        try:
            existing = read_existing_site_data()
            generated_at = str(existing.get("generatedAt", "")).strip()
        except json.JSONDecodeError:
            generated_at = ""

    return {
        "generated_at": generated_at,
        "declaration": {
            "title": "特别声明",
            "subtitle": "以下结果基于同一批本机聚合日志、同一费用口径与同一评分权重做横向对比。",
            "conclusion": [
                "建议优先使用官方渠道，目前获取方式相对还算简单，网上已有较多教程，这里不再赘述。中转站更适合作为备用选项，不建议作为长期主力方案。",
                "中转站服务质量参差不齐，普遍存在错误响应率更高、响应时间更长、稳定性更差等问题。同时，计费规则不够透明，价格倍率也可能频繁变动。",
                "中转站还存在模型质量不稳定、计费不清晰、数据安全风险较高，以及随时关停或跑路的风险。如确需使用，建议少量多次充值，控制损失风险。",
            ],
            "items": [
                "工作时段：每日 09:00:00-18:00:00。",
                "非工作时段：每日 18:00:01-次日 08:59:59。",
                "正式综合排名仅使用高置信度或人工核验的费用证据；0 倍率分组不参与排名。",
                DISCLAIMER_EMPHASIS,
            ],
            "environment": "\n\n".join(
                [
                    "本次数据来自本人电脑上 Codex Manager 对多家中转站 Codex API Key 的聚合调用日志，使用场景为 Codex 接入开发。",
                    "由于所有请求均先经过 Codex Manager，再转发至各中转站，相比直连会天然增加一层延迟。",
                    f"费用口径统一按各站当前可核验的最低倍率档位计算。该档位通常价格最低，但也往往延迟更高、稳定性更差，{HIGHLIGHT_PHRASE}",
                    "日志样本来自本人实际开发个人小项目期间的调用记录，网络环境为昆明广电宽带。以下排名仅反映本人使用时间点、当时账号状态与当时网络环境下的观测结果。",
                ]
            ),
            "coreItems": [
                "综合评分权重 = 正确响应率 40% + 响应时间 35% + 实际倍率 25%。",
                "实际倍率 = 分组倍率 × 实付人民币 ÷ 到账美元额度。",
                "正式采用倍率：该站点所有已核验、非 0、可参与排名档位中的最低实际倍率。",
                "正确响应定义：HTTP 2xx 且 error IS NULL；HTTP 200 但 error 非空也计为错误响应；因欠费、充值解锁、手机号验证等账户前置条件导致的错误样本，已从正确响应率统计中剔除。",
            ],
            "formula": "实际倍率 = 分组倍率 × 实付人民币 ÷ 到账美元额度。",
            "adoptedMultiplierRule": "正式采用倍率：该站点所有已核验、非 0、可参与排名档位中的最低实际倍率。",
            "scoring": "综合评分权重 = 正确响应率 40% + 响应时间 35% + 实际倍率 25%。",
        },
    }


def ranking_row(row: dict[str, str]) -> dict[str, Any]:
    adopted_tier = sanitize_public_text(row.get("adopted_tier"))
    adopted_group, adopted_recharge = (adopted_tier.split(" | ", 1) + [""])[:2] if adopted_tier else ("", "")
    station_type = row.get("station_type", "unknown_pending")
    return {
        "rank": parse_int(row.get("rank")),
        "rankingBasis": sanitize_public_text(row.get("ranking_basis")),
        "timeWindow": row.get("time_window", ""),
        "timeWindowLabel": sanitize_public_text(row.get("time_window_label")),
        "station": row.get("station", ""),
        "label": sanitize_public_text(row.get("label")),
        "stationUrl": sanitize_public_text(row.get("station_url")),
        "stationType": station_type,
        "stationTypeLabel": sanitize_public_text(row.get("station_type_label")) or FULL_TYPE_LABELS.get(station_type, station_type),
        "stationTypeShortLabel": SHORT_TYPE_LABELS.get(station_type, station_type),
        "totalScore": parse_float(row.get("total_score")) or 0.0,
        "successScore": parse_float(row.get("success_score")) or 0.0,
        "latencyScore": parse_float(row.get("latency_score")) or 0.0,
        "costScore": parse_float(row.get("cost_score")) or 0.0,
        "correctRate": parse_float(row.get("correct_rate")) or 0.0,
        "avgSeconds": parse_float(row.get("avg_seconds")) or 0.0,
        "medianSeconds": parse_float(row.get("median_seconds")),
        "p95Seconds": parse_float(row.get("p95_seconds")),
        "effectiveMultiplier": parse_float(row.get("effective_multiplier")) or 0.0,
        "feeVerified": parse_bool(row.get("fee_verified")),
        "adoptedTier": adopted_tier,
        "adoptedGroup": adopted_group,
        "adoptedRechargeName": adopted_recharge,
        "billingType": row.get("billing_type", ""),
        "billingTypeLabel": sanitize_public_text(row.get("billing_type_label")) or BILLING_LABELS.get(row.get("billing_type", ""), ""),
        "multiplierFullUseAssumption": sanitize_public_text(row.get("multiplier_full_use_assumption")),
        "requests": parse_int(row.get("requests")),
        "correct": parse_int(row.get("correct")),
        "failures": parse_int(row.get("failures")),
        "http2xx": parse_int(row.get("http_2xx")),
        "http200WithError": parse_int(row.get("http_200_with_error")),
        "firstAt": row.get("first_at", ""),
        "lastAt": row.get("last_at", ""),
    }


def quality_row(row: dict[str, str]) -> dict[str, Any]:
    return {
        "station": row.get("station", ""),
        "label": sanitize_public_text(row.get("label")),
        "platformGuess": sanitize_public_text(row.get("platform_guess")),
        "timeWindow": row.get("time_window", ""),
        "timeWindowLabel": sanitize_public_text(row.get("time_window_label")),
        "requestSamples": parse_int(row.get("request_samples")),
        "correct": parse_int(row.get("correct")),
        "failures": parse_int(row.get("failures")),
        "correctRate": parse_float(row.get("correct_rate")) or 0.0,
        "http2xx": parse_int(row.get("http_2xx")),
        "http200WithError": parse_int(row.get("http_200_with_error")),
        "nonnullError": parse_int(row.get("nonnull_error")),
        "excludedBillingErrors": parse_int(row.get("excluded_billing_errors")),
        "avgSeconds": parse_float(row.get("avg_seconds")),
        "medianSeconds": parse_float(row.get("median_seconds")),
        "p95Seconds": parse_float(row.get("p95_seconds")),
        "avgFirstResponseSeconds": parse_float(row.get("avg_first_response_seconds")),
        "firstAt": row.get("first_at", ""),
        "lastAt": row.get("last_at", ""),
    }


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def audit_sort_datetime(value: Any) -> datetime:
    return parse_iso_datetime(value) or datetime.min.replace(tzinfo=UTC)


def normalize_audit_step_summary(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    title = sanitize_public_text(item.get("title"))
    summary = normalize_public_text(item.get("summary"))
    if not title or not summary:
        return None
    return {"title": title, "summary": summary}


def normalize_audit_summary(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    profile = str(item.get("profile") or "").strip()
    model = sanitize_public_text(item.get("model"))
    executed_at = str(item.get("executedAt") or "").strip()
    report_path = sanitize_public_text(item.get("reportPath"))
    run_status = str(item.get("runStatus") or "success").strip()
    if profile != "general" or not model or not executed_at or not report_path:
        return None
    if run_status != "success":
        return None
    overall_verdict = str(item.get("overallVerdict") or "").strip().lower()
    if overall_verdict not in {"low", "medium", "high", "inconclusive"}:
        overall_verdict = "inconclusive"
    highlights = [normalize_public_text(value) for value in item.get("highlights", []) if normalize_public_text(value)]
    steps = []
    for raw_step in item.get("stepSummaries", []):
        step = normalize_audit_step_summary(raw_step)
        if step:
            steps.append(step)
    payload = {
        "profile": "general",
        "model": model,
        "auditedBaseUrl": sanitize_public_text(item.get("auditedBaseUrl")),
        "executedAt": executed_at,
        "overallVerdict": overall_verdict,
        "overallSummary": normalize_public_text(item.get("overallSummary")),
        "highlights": highlights,
        "stepSummaries": steps,
        "reportPath": report_path,
        "toolVersion": sanitize_public_text(item.get("toolVersion")),
    }
    duration_ms = parse_int(item.get("durationMs")) if item.get("durationMs") is not None else None
    if duration_ms is not None:
        payload["durationMs"] = duration_ms
    engine_commit = sanitize_public_text(item.get("engineCommit"))
    if engine_commit:
        payload["engineCommit"] = engine_commit
    effective_options = item.get("effectiveOptions")
    if isinstance(effective_options, dict):
        payload["effectiveOptions"] = effective_options
    return payload


def audit_run_status_for_summary(path: Path) -> str:
    run_path = path.with_name("run.json")
    if not run_path.exists():
        return "success"
    try:
        payload = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "failed"
    return str(payload.get("status") or "failed").strip()


def ensure_station(container: dict[str, dict[str, Any]], station_key: str, **overrides: Any) -> dict[str, Any]:
    station_type = overrides.get("station_type") or "unknown_pending"
    record = container.setdefault(
        station_key,
        {
            "key": station_key,
            "label": sanitize_public_text(overrides.get("label")) or station_key,
            "url": sanitize_public_text(overrides.get("url")),
            "stationType": station_type,
            "stationTypeLabel": FULL_TYPE_LABELS.get(station_type, "待补证据"),
            "stationTypeShortLabel": SHORT_TYPE_LABELS.get(station_type, "待补证据"),
            "platformGuess": sanitize_public_text(overrides.get("platform_guess")),
            "verifiedTierCount": 0,
            "groupMultipliers": [],
            "rechargeTiers": [],
            "tierNotes": [],
            "announcements": [],
            "rankings": {},
            "quality": {},
        },
    )

    if overrides.get("label"):
        record["label"] = sanitize_public_text(overrides["label"])
    if overrides.get("url"):
        record["url"] = sanitize_public_text(overrides["url"])

    station_type = overrides.get("station_type")
    if station_type:
        record["stationType"] = station_type
        record["stationTypeLabel"] = FULL_TYPE_LABELS.get(station_type, station_type)
        record["stationTypeShortLabel"] = SHORT_TYPE_LABELS.get(station_type, station_type)

    if overrides.get("platform_guess"):
        record["platformGuess"] = sanitize_public_text(overrides["platform_guess"])

    record.setdefault("groupMultipliers", [])
    record.setdefault("rechargeTiers", [])
    record.setdefault("tierNotes", [])
    record.setdefault("announcements", [])
    record.setdefault("rankings", {})
    record.setdefault("quality", {})
    record.setdefault("verifiedTierCount", 0)
    return record


def empty_rankings() -> dict[str, list[dict[str, Any]]]:
    return {window_key: [] for window_key in TIME_WINDOWS}


def load_status_payloads() -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    fetch_dirs = [path for path in PUBLIC_FETCH_DIRS if path.exists()]
    if not fetch_dirs:
        return grouped

    for fetch_dir in fetch_dirs:
        for path in sorted(fetch_dir.glob("*_status.json")):
            station_key = path.stem.replace("_status", "")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                grouped[station_key] = payload
    return grouped


def load_announcements(status_payloads: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for station_key, payload in status_payloads.items():
        data = payload.get("data") if isinstance(payload, dict) else {}
        announcements = data.get("announcements") if isinstance(data, dict) else []
        if not isinstance(announcements, list):
            continue

        source_url = sanitize_public_text(str(data.get("server_address") or ""))
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(announcements, start=1):
            if not isinstance(item, dict):
                continue
            content = normalize_public_text(item.get("content"))
            if not content:
                continue
            rows.append(
                {
                    "id": str(item.get("id") or index),
                    "publishedAt": str(item.get("publishDate") or ""),
                    "type": sanitize_public_text(item.get("type") or "default"),
                    "extra": normalize_public_text(item.get("extra")),
                    "content": content,
                    "sourceUrl": source_url,
                }
            )
        grouped[station_key] = rows
    return grouped


def normalize_group_row(item: dict[str, Any]) -> dict[str, Any] | None:
    group_name = sanitize_public_text(item.get("groupName") or item.get("group_name"))
    group_multiplier = parse_float(item.get("groupMultiplier") if "groupMultiplier" in item else item.get("group_multiplier"))
    if not group_name or group_multiplier is None:
        return None
    return {
        "groupName": group_name,
        "groupMultiplier": group_multiplier,
    }


def normalize_recharge_row(item: dict[str, Any]) -> dict[str, Any] | None:
    recharge_name = sanitize_public_text(item.get("rechargeName") or item.get("recharge_name") or item.get("name") or item.get("title") or item.get("label"))
    billing_type = sanitize_public_text(item.get("billingType") or item.get("billing_type") or "permanent")
    rmb_amount = parse_float(
        item.get("rmbAmount")
        if "rmbAmount" in item
        else item.get("rmb_amount", item.get("rmb", item.get("cny_amount", item.get("amount"))))
    )
    usd_amount = parse_float(
        item.get("usdAmount")
        if "usdAmount" in item
        else item.get("usd_amount", item.get("usd", item.get("quota", item.get("amount_usd"))))
    )
    if not recharge_name or rmb_amount is None or usd_amount is None:
        return None
    recharge_location = sanitize_public_text(item.get("rechargeLocation") or item.get("recharge_location") or item.get("location"))
    expires_rule = sanitize_public_text(item.get("expiresRule") or item.get("expires_rule") or item.get("note"))
    return {
        "rechargeName": recharge_name,
        "billingType": billing_type,
        "billingTypeLabel": sanitize_public_text(item.get("billingTypeLabel") or item.get("billing_type_label")) or BILLING_LABELS.get(billing_type, billing_type or "未知"),
        "rmbAmount": rmb_amount,
        "usdAmount": usd_amount,
        "rechargeLocation": recharge_location,
        "expiresRule": expires_rule,
    }


def group_row_key(group: dict[str, Any]) -> tuple[str, float]:
    return (str(group.get("groupName", "")), float(group.get("groupMultiplier", 0.0)))


def recharge_row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("rechargeName", ""),
        row.get("billingType", ""),
        row.get("rmbAmount"),
        row.get("usdAmount"),
        row.get("rechargeLocation", ""),
        row.get("expiresRule", ""),
    )


def append_group_row(station: dict[str, Any], group: dict[str, Any]) -> None:
    existing = {group_row_key(item) for item in station.get("groupMultipliers", [])}
    key = group_row_key(group)
    if key not in existing:
        station["groupMultipliers"].append(group)


def append_recharge_row(station: dict[str, Any], row: dict[str, Any]) -> None:
    existing = {recharge_row_key(item) for item in station.get("rechargeTiers", [])}
    key = recharge_row_key(row)
    if key not in existing:
        station["rechargeTiers"].append(row)


def load_base_site_snapshot() -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, set[str]]]:
    existing = read_existing_site_data()
    rankings = empty_rankings()
    for window_key in TIME_WINDOWS:
        rankings[window_key] = [deepcopy(row) for row in existing.get("rankings", {}).get(window_key, [])]

    stations: dict[str, dict[str, Any]] = {}
    station_urls: dict[str, set[str]] = {}
    for raw_station in existing.get("stations", []):
        station_key = str(raw_station.get("key") or "").strip()
        if not station_key:
            continue
        station = ensure_station(
            stations,
            station_key,
            label=raw_station.get("label", ""),
            url=raw_station.get("url", ""),
            station_type=raw_station.get("stationType", ""),
            platform_guess=raw_station.get("platformGuess", ""),
        )
        station.update(deepcopy(raw_station))
        station.setdefault("groupMultipliers", [])
        station.setdefault("rechargeTiers", [])
        station.setdefault("tierNotes", [])
        station.setdefault("announcements", [])
        station.setdefault("quality", {})
        station.setdefault("rankings", {})
        station.setdefault("verifiedTierCount", 0)
        station.setdefault("audits", None)
        if station.get("url"):
            station_urls.setdefault(station_key, set()).add(sanitize_public_text(station["url"]))
        for announcement in station.get("announcements", []):
            source_url = sanitize_public_text(announcement.get("sourceUrl"))
            if source_url:
                station_urls.setdefault(station_key, set()).add(source_url)

    sync_station_rankings_from_rankings(stations, rankings)
    return rankings, stations, station_urls


def reset_station_tiers(stations: dict[str, dict[str, Any]]) -> None:
    for station in stations.values():
        station["verifiedTierCount"] = 0
        station["groupMultipliers"] = []
        station["rechargeTiers"] = []
        station["tierNotes"] = []


def sync_station_rankings_from_rankings(stations: dict[str, dict[str, Any]], rankings: dict[str, list[dict[str, Any]]]) -> None:
    for station in stations.values():
        station["rankings"] = {}

    for window_key, rows in rankings.items():
        for row in rows:
            station = ensure_station(
                stations,
                row.get("station", ""),
                label=row.get("label", ""),
                url=row.get("stationUrl", ""),
                station_type=row.get("stationType", ""),
            )
            station["rankings"][window_key] = row


def maybe_parse_group_ratio(group_name: str, raw_value: Any) -> dict[str, Any] | None:
    if isinstance(raw_value, dict):
        raw_value = raw_value.get("ratio") or raw_value.get("multiplier") or raw_value.get("value")
    group_multiplier = parse_float(raw_value)
    if group_multiplier is None:
        return None
    return {"groupName": sanitize_public_text(group_name), "groupMultiplier": group_multiplier}


def parse_pricing_tier_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    signal_fields = [
        item.get("recharge_name"),
        item.get("rechargeName"),
        item.get("name"),
        item.get("title"),
        item.get("label"),
        item.get("description"),
        item.get("quota"),
        item.get("usd"),
        item.get("usd_amount"),
    ]
    signal = " ".join(str(field or "") for field in signal_fields).lower()
    if not any(marker in signal for marker in ("topup", "recharge", "充值", "额度", "wallet")) and "quota" not in item:
        return None

    row = normalize_recharge_row(item)
    if row:
        return row

    rmb_amount = parse_float(item.get("amount") or item.get("money") or item.get("price"))
    usd_amount = parse_float(item.get("quota") or item.get("credit"))
    if rmb_amount is None or usd_amount is None:
        return None

    recharge_name = sanitize_public_text(item.get("name") or item.get("title") or item.get("label")) or f"wallet topup {format_plain_number(rmb_amount)} RMB"
    return normalize_recharge_row(
        {
            "rechargeName": recharge_name,
            "billingType": item.get("billingType") or item.get("billing_type") or "permanent",
            "rmbAmount": rmb_amount,
            "usdAmount": usd_amount,
            "rechargeLocation": item.get("rechargeLocation") or item.get("recharge_location") or "public pricing snapshot",
            "expiresRule": item.get("expiresRule") or item.get("expires_rule") or "",
        }
    )


def parse_public_pricing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    recharge_tiers: list[dict[str, Any]] = []
    tier_notes: list[str] = []
    source_url = sanitize_public_text(payload.get("server_address") or payload.get("base_url") or payload.get("source_url"))

    group_ratio = payload.get("group_ratio")
    if isinstance(group_ratio, dict):
        for group_name, raw_value in group_ratio.items():
            group = maybe_parse_group_ratio(group_name, raw_value)
            if group:
                groups.append(group)

    for key in ("recharge_tiers", "topup_tiers", "topups", "wallet_topups", "pricing_tiers", "data"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            tier = parse_pricing_tier_item(item)
            if tier:
                recharge_tiers.append(tier)

    note = normalize_public_text(payload.get("message"))
    if note:
        tier_notes.append(note)

    return {
        "groupMultipliers": groups,
        "rechargeTiers": recharge_tiers,
        "tierNotes": tier_notes,
        "sourceUrl": source_url,
    }


def parse_public_pricing_html(content: str) -> dict[str, Any]:
    recharge_tiers: list[dict[str, Any]] = []
    for match in TOPUP_HTML_PATTERN.finditer(content):
        recharge_name = sanitize_public_text(match.group(1))
        rmb_amount = parse_float(match.group(2))
        usd_amount = parse_float(match.group(3))
        row = normalize_recharge_row(
            {
                "rechargeName": recharge_name,
                "billingType": "permanent",
                "rmbAmount": rmb_amount,
                "usdAmount": usd_amount,
                "rechargeLocation": "public pricing page",
                "expiresRule": "",
            }
        )
        if row:
            recharge_tiers.append(row)

    return {
        "groupMultipliers": [],
        "rechargeTiers": recharge_tiers,
        "tierNotes": [],
        "sourceUrl": "",
    }


def load_public_pricing_snapshots() -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    fetch_dirs = [path for path in PUBLIC_FETCH_DIRS if path.exists()]
    if not fetch_dirs:
        return grouped

    for fetch_dir in fetch_dirs:
        for path in sorted(fetch_dir.glob("*_pricing.*")):
            station_key = path.stem.replace("_pricing", "")
            parsed = {
                "groupMultipliers": [],
                "rechargeTiers": [],
                "tierNotes": [],
                "sourceUrl": "",
            }
            try:
                content = path.read_text(encoding="utf-8")
                if path.suffix.lower() == ".json":
                    payload = json.loads(content)
                    if isinstance(payload, dict):
                        parsed = parse_public_pricing_payload(payload)
                else:
                    parsed = parse_public_pricing_html(content)
            except (OSError, json.JSONDecodeError):
                continue

            if not parsed["groupMultipliers"] and not parsed["rechargeTiers"] and not parsed["tierNotes"]:
                continue

            bucket = grouped.setdefault(
                station_key,
                {"groupMultipliers": [], "rechargeTiers": [], "tierNotes": [], "sourceUrl": parsed["sourceUrl"]},
            )
            if parsed["sourceUrl"]:
                bucket["sourceUrl"] = parsed["sourceUrl"]
            existing_groups = {group_row_key(item) for item in bucket["groupMultipliers"]}
            for group in parsed["groupMultipliers"]:
                key = group_row_key(group)
                if key not in existing_groups:
                    bucket["groupMultipliers"].append(group)
                    existing_groups.add(key)
            existing_tiers = {recharge_row_key(item) for item in bucket["rechargeTiers"]}
            for tier in parsed["rechargeTiers"]:
                key = recharge_row_key(tier)
                if key not in existing_tiers:
                    bucket["rechargeTiers"].append(tier)
                    existing_tiers.add(key)
            for note in parsed["tierNotes"]:
                if note and note not in bucket["tierNotes"]:
                    bucket["tierNotes"].append(note)
    return grouped


def load_station_audit_targets() -> dict[str, dict[str, Any]]:
    if not STATION_AUDIT_TARGETS_PATH.exists():
        return {}
    payload = json.loads(STATION_AUDIT_TARGETS_PATH.read_text(encoding="utf-8"))
    targets = payload.get("targets") if isinstance(payload, dict) else None
    if not isinstance(targets, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in targets:
        if not isinstance(item, dict):
            continue
        station_key = str(item.get("station") or "").strip()
        if not station_key:
            continue
        models = [sanitize_public_text(model) for model in item.get("models", []) if sanitize_public_text(model)]
        default_model = sanitize_public_text(item.get("defaultModel")) or (models[0] if models else "")
        result[station_key] = {
            "defaultModel": default_model,
            "availableModels": models,
        }
    return result


def load_latest_station_audits() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, tuple[datetime | None, dict[str, Any]]]] = {}
    if not AUDIT_RUNS_DIR.exists():
        return {}
    for path in AUDIT_RUNS_DIR.glob("*/*/*/summary.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if audit_run_status_for_summary(path) != "success":
            continue
        summary = normalize_audit_summary(payload)
        if not summary:
            continue
        parts = path.relative_to(AUDIT_RUNS_DIR).parts
        if len(parts) < 4:
            continue
        station_key = parts[0]
        model_bucket = grouped.setdefault(station_key, {})
        executed_at = parse_iso_datetime(summary["executedAt"])
        existing = model_bucket.get(summary["model"])
        if existing:
            existing_time = existing[0] or datetime.min.replace(tzinfo=UTC)
            next_time = executed_at or datetime.min.replace(tzinfo=UTC)
            if existing_time >= next_time:
                continue
        if existing and existing[0] and not executed_at:
            continue
        model_bucket[summary["model"]] = (executed_at, summary)

    latest: dict[str, list[dict[str, Any]]] = {}
    for station_key, by_model in grouped.items():
        rows = [summary for _dt, summary in by_model.values()]
        rows.sort(key=lambda item: audit_sort_datetime(item.get("executedAt")), reverse=True)
        latest[station_key] = rows
    return latest


def audit_station_label_from_base_url(value: Any, fallback: str) -> str:
    parsed = urlparse(sanitize_public_text(value))
    host = parsed.netloc.lower().removeprefix("www.")
    return host or fallback


def apply_audit_only_station_records(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    latest_audits: dict[str, list[dict[str, Any]]],
) -> None:
    for station_key, audit_rows in latest_audits.items():
        if not audit_rows:
            continue

        audited_base_url = sanitize_public_text(audit_rows[0].get("auditedBaseUrl"))
        if station_key in stations:
            station = ensure_station(stations, station_key)
            if audited_base_url and not station.get("url"):
                station["url"] = audited_base_url
        else:
            station = ensure_station(
                stations,
                station_key,
                label=audit_station_label_from_base_url(audited_base_url, station_key),
                url=audited_base_url,
            )

        if audited_base_url:
            station_urls.setdefault(station_key, set()).add(audited_base_url)


def load_station_pricing_overrides() -> dict[str, dict[str, Any]]:
    if not STATION_PRICING_OVERRIDES_PATH.exists():
        return {}
    payload = json.loads(STATION_PRICING_OVERRIDES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {str(station_key): value for station_key, value in payload.items() if isinstance(value, dict)}


def apply_public_pricing_snapshots(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    pricing_snapshots: dict[str, dict[str, Any]],
) -> None:
    for station_key, snapshot in pricing_snapshots.items():
        station = ensure_station(stations, station_key)
        source_url = sanitize_public_text(snapshot.get("sourceUrl"))
        if source_url:
            station_urls.setdefault(station_key, set()).add(source_url)
        for group in snapshot.get("groupMultipliers", []):
            append_group_row(station, group)
        for tier in snapshot.get("rechargeTiers", []):
            append_recharge_row(station, tier)
        for note in snapshot.get("tierNotes", []):
            normalized = normalize_public_text(note)
            if normalized and normalized not in station["tierNotes"]:
                station["tierNotes"].append(normalized)


def sort_recharge_tiers(recharge_tiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        recharge_tiers,
        key=lambda tier: (
            tier.get("rmbAmount") is None,
            tier.get("rmbAmount") if tier.get("rmbAmount") is not None else float("inf"),
            tier.get("rechargeName", ""),
        ),
    )


def apply_station_pricing_overrides(
    stations: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> None:
    for station_key, override in overrides.items():
        station = ensure_station(stations, station_key)

        group_rows = []
        for item in override.get("groupMultipliers", []):
            if isinstance(item, dict):
                normalized = normalize_group_row(item)
                if normalized:
                    group_rows.append(normalized)
        if group_rows:
            station["groupMultipliers"] = group_rows

        recharge_mode = override.get("rechargeMode")
        if recharge_mode == "linear_rmb_to_usd":
            usd_per_rmb = parse_float(override.get("usdPerRmb")) or 0.0
            recharge_pattern = re.compile(str(override.get("rechargeNamePattern") or TOPUP_NAME_PATTERN.pattern), re.IGNORECASE)
            updated_tiers: list[dict[str, Any]] = []
            for tier in station.get("rechargeTiers", []):
                next_tier = deepcopy(tier)
                if recharge_pattern.search(next_tier.get("rechargeName", "")) and next_tier.get("rmbAmount") is not None and usd_per_rmb > 0:
                    next_tier["usdAmount"] = round(float(next_tier["rmbAmount"]) * usd_per_rmb, 10)
                updated_tiers.append(next_tier)
            station["rechargeTiers"] = sort_recharge_tiers(updated_tiers)

        assumption_text = sanitize_public_text(override.get("assumptionText"))
        if assumption_text and assumption_text not in station["tierNotes"]:
            station["tierNotes"].append(assumption_text)


def find_group_row(station: dict[str, Any], group_name: str) -> dict[str, Any] | None:
    for group in station.get("groupMultipliers", []):
        if group.get("groupName") == group_name:
            return group
    return None


def find_recharge_row(station: dict[str, Any], recharge_name: str) -> dict[str, Any] | None:
    for tier in station.get("rechargeTiers", []):
        if tier.get("rechargeName") == recharge_name:
            return tier
    return None


def calculate_effective_multiplier(group_multiplier: float | None, recharge_row: dict[str, Any]) -> float | None:
    rmb_amount = parse_float(recharge_row.get("rmbAmount"))
    usd_amount = parse_float(recharge_row.get("usdAmount"))
    if group_multiplier is None or rmb_amount is None or usd_amount in (None, 0):
        return None
    return float(group_multiplier) * rmb_amount / usd_amount


def recompute_ranking_window(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    effective_values = [float(row.get("effectiveMultiplier", 0.0)) for row in rows]
    min_eff = min(effective_values)
    max_eff = max(effective_values)
    same_eff = abs(max_eff - min_eff) < 1e-12

    for row in rows:
        effective_multiplier = float(row.get("effectiveMultiplier", 0.0))
        if same_eff:
            cost_score = 100.0
        else:
            cost_score = 100.0 * (max_eff - effective_multiplier) / (max_eff - min_eff)
            cost_score = max(0.0, min(100.0, cost_score))
        row["_originalRank"] = row.get("rank", 10**9)
        row["costScore"] = cost_score
        row["totalScore"] = 0.4 * float(row.get("successScore", 0.0)) + 0.35 * float(row.get("latencyScore", 0.0)) + 0.25 * cost_score

    rows.sort(
        key=lambda row: (
            -float(row.get("totalScore", 0.0)),
            -float(row.get("successScore", 0.0)),
            -float(row.get("latencyScore", 0.0)),
            float(row.get("effectiveMultiplier", 0.0)),
            int(row.get("_originalRank", 10**9)),
        )
    )

    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row.pop("_originalRank", None)


def apply_authoritative_ranking_overrides(
    stations: dict[str, dict[str, Any]],
    rankings: dict[str, list[dict[str, Any]]],
    overrides: dict[str, dict[str, Any]],
) -> None:
    authoritative_stations = [station_key for station_key, override in overrides.items() if parse_bool(override.get("authoritative"))]
    if not authoritative_stations:
        return

    for station_key in authoritative_stations:
        station = stations.get(station_key)
        if not station:
            continue

        forced_tier = sanitize_public_text(overrides[station_key].get("forcedAdoptedTier"))
        if not forced_tier or " | " not in forced_tier:
            continue
        adopted_group, adopted_recharge = forced_tier.split(" | ", 1)

        group = find_group_row(station, adopted_group)
        recharge_row = find_recharge_row(station, adopted_recharge)
        if not group or not recharge_row:
            continue

        effective_multiplier = calculate_effective_multiplier(group.get("groupMultiplier"), recharge_row)
        if effective_multiplier is None:
            continue

        assumption_text = sanitize_public_text(overrides[station_key].get("assumptionText")) or recharge_row.get("expiresRule", "")
        if assumption_text and assumption_text not in station["tierNotes"]:
            station["tierNotes"].append(assumption_text)

        for rows in rankings.values():
            for row in rows:
                if row.get("station") != station_key:
                    continue
                row["effectiveMultiplier"] = effective_multiplier
                row["adoptedTier"] = forced_tier
                row["adoptedGroup"] = adopted_group
                row["adoptedRechargeName"] = adopted_recharge
                row["billingType"] = recharge_row.get("billingType", "")
                row["billingTypeLabel"] = recharge_row.get("billingTypeLabel", "")
                row["multiplierFullUseAssumption"] = assumption_text
                row["feeVerified"] = True

    for rows in rankings.values():
        recompute_ranking_window(rows)

    sync_station_rankings_from_rankings(stations, rankings)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    intro = load_summary_intro()
    required_inputs = [
        "composite_ranking_formal_workhours.csv",
        "composite_ranking_formal_offhours.csv",
        "composite_ranking_formal_all_hours.csv",
        "quality_metrics.csv",
        "login_verification_checklist.csv",
        "multiplier_tiers.csv",
    ]
    resolved_inputs = {name: resolve_source_path(name) for name in required_inputs}
    missing_inputs = [name for name, path in resolved_inputs.items() if path is None]

    use_existing_base = bool(missing_inputs)
    if use_existing_base:
        if not SITE_DATA_PATH.exists():
            missing = ", ".join(missing_inputs)
            raise FileNotFoundError(f"Missing required source files and no existing site-data.json to reuse: {missing}")
        rankings, stations, station_urls = load_base_site_snapshot()
    else:
        rankings = empty_rankings()
        stations = {}
        station_urls = {}

    ranking_inputs = {
        "work_hours": resolved_inputs.get("composite_ranking_formal_workhours.csv"),
        "off_hours": resolved_inputs.get("composite_ranking_formal_offhours.csv"),
        "all_hours": resolved_inputs.get("composite_ranking_formal_all_hours.csv"),
    }
    for window_key, input_path in ranking_inputs.items():
        if not input_path:
            continue
        rankings[window_key] = [ranking_row(row) for row in read_csv(input_path)]

    if resolved_inputs.get("login_verification_checklist.csv"):
        checklist_rows = read_csv(resolved_inputs["login_verification_checklist.csv"])
        for row in checklist_rows:
            urls = [sanitize_public_text(url) for url in split_list(row.get("urls"))]
            station_key = row.get("station", "")
            if not station_key:
                continue
            ensure_station(
                stations,
                station_key,
                label=row.get("label", ""),
                url=urls[0] if urls else "",
                station_type=row.get("station_type", ""),
                platform_guess=row.get("platform_guess", ""),
            )
            station_urls.setdefault(station_key, set()).update(urls)
            probe_final_url = sanitize_public_text(row.get("probe_final_url"))
            if probe_final_url:
                station_urls.setdefault(station_key, set()).add(probe_final_url)

    sync_station_rankings_from_rankings(stations, rankings)
    for window_rows in rankings.values():
        for row in window_rows:
            if row.get("stationUrl"):
                station_urls.setdefault(row["station"], set()).add(row["stationUrl"])

    if resolved_inputs.get("quality_metrics.csv"):
        for station in stations.values():
            station["quality"] = {}
        quality_rows = [quality_row(row) for row in read_csv(resolved_inputs["quality_metrics.csv"])]
        for row in quality_rows:
            station = ensure_station(
                stations,
                row["station"],
                label=row["label"],
                platform_guess=row["platformGuess"],
            )
            station["quality"][row["timeWindow"]] = row
            configured_url = station_url(row.get("configured_urls"))
            if configured_url:
                station_urls.setdefault(row["station"], set()).add(configured_url)

    if resolved_inputs.get("multiplier_tiers.csv"):
        reset_station_tiers(stations)
        tier_rows = read_csv(resolved_inputs["multiplier_tiers.csv"])
        for row in tier_rows:
            station_key = row.get("station", "")
            if not station_key:
                continue

            station = ensure_station(
                stations,
                station_key,
                label=row.get("label", ""),
                station_type=row.get("station_type", ""),
            )
            station["verifiedTierCount"] += 1

            group = normalize_group_row({"group_name": row.get("group_name"), "group_multiplier": row.get("group_multiplier")})
            if group:
                append_group_row(station, group)

            recharge = normalize_recharge_row(
                {
                    "recharge_name": row.get("recharge_name"),
                    "billing_type": row.get("billing_type"),
                    "billing_type_label": BILLING_LABELS.get(row.get("billing_type", ""), sanitize_public_text(row.get("billing_type") or "未知")),
                    "rmb_amount": row.get("rmb_amount"),
                    "usd_amount": row.get("usd_amount"),
                    "recharge_location": row.get("recharge_location"),
                    "expires_rule": row.get("expires_rule"),
                }
            )
            if recharge:
                append_recharge_row(station, recharge)

            note = normalize_public_text(row.get("notes"))
            if note and note not in station["tierNotes"]:
                station["tierNotes"].append(note)

            evidence_url = sanitize_public_text(row.get("evidence_url"))
            if evidence_url:
                station_urls.setdefault(station_key, set()).add(evidence_url)

    status_payloads = load_status_payloads()
    announcements = load_announcements(status_payloads)
    for station_key, payload in status_payloads.items():
        data = payload.get("data") if isinstance(payload, dict) else {}
        if isinstance(data, dict):
            source_url = sanitize_public_text(data.get("server_address"))
            if source_url:
                station_urls.setdefault(station_key, set()).add(source_url)

    pricing_snapshots = load_public_pricing_snapshots()
    apply_public_pricing_snapshots(stations, station_urls, pricing_snapshots)

    overrides = load_station_pricing_overrides()
    apply_station_pricing_overrides(stations, overrides)

    audit_targets = load_station_audit_targets()
    latest_audits = load_latest_station_audits()
    apply_audit_only_station_records(stations, station_urls, latest_audits)

    for station_key, rows in announcements.items():
        station = ensure_station(stations, station_key)
        station["announcements"] = rows

    apply_authoritative_ranking_overrides(stations, rankings, overrides)

    station_list = sorted(
        stations.values(),
        key=lambda item: (
            item.get("rankings", {}).get("work_hours", {}).get("rank", 10**9),
            item.get("label", "").lower(),
        ),
    )

    for station in station_list:
        station["rechargeTiers"] = sort_recharge_tiers(station.get("rechargeTiers", []))
        url_choices = dedupe_strings(list(station_urls.get(station["key"], set())) + [station.get("url", "")])
        station["url"] = choose_best_url(url_choices)
        audit_rows = latest_audits.get(station["key"], [])
        audit_target = audit_targets.get(station["key"], {})
        if audit_rows or audit_target:
            available_models = dedupe_strings(
                list(audit_target.get("availableModels", [])) + [row.get("model", "") for row in audit_rows if row.get("model")]
            )
            latest_audit_at = ""
            if audit_rows:
                latest_audit_at = max((row.get("executedAt", "") for row in audit_rows), default="")
            station["audits"] = {
                "defaultModel": sanitize_public_text(audit_target.get("defaultModel")) or (audit_rows[0]["model"] if audit_rows else ""),
                "availableModels": available_models,
                "latestByModel": audit_rows,
                "latestAuditAt": latest_audit_at or None,
            }
        else:
            station.pop("audits", None)

    site_data = {
        "siteName": "中转站监视者",
        "projectName": "api-relay-rank",
        "generatedAt": intro["generated_at"],
        "timezone": "Asia/Shanghai",
        "defaultTimeWindow": "work_hours",
        "defaultSort": "composite",
        "declaration": intro["declaration"],
        "timeWindows": TIME_WINDOWS,
        "rankings": rankings,
        "stations": station_list,
        "rankedStationCount": {window: len(rows) for window, rows in rankings.items()},
    }

    SITE_DATA_PATH.write_text(json.dumps(site_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "generated_at": intro["generated_at"],
                "output": str(SITE_DATA_PATH),
                "stations": len(station_list),
                "work_hours_ranked": len(rankings["work_hours"]),
                "off_hours_ranked": len(rankings["off_hours"]),
                "reused_existing": use_existing_base,
                "missing_sources": missing_inputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
