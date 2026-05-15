#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
DATA_DIR = APP_ROOT / "data"
PUBLIC_FETCH_DIR = WORKSPACE_ROOT / "_public_fetch"

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

HIGHLIGHT_PHRASE = "所以此排名关注的是中转站的的服务下限"
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
PATH_PATTERN = re.compile(r"([A-Za-z]:\\Users\\)([^\\`]+)")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_float(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: str | None) -> int:
    number = parse_float(value)
    return int(number or 0)


def parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def split_list(value: str | None) -> list[str]:
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


def sanitize_public_text(value: str | None) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = PATH_PATTERN.sub(r"\1xxx", text)
    text = EMAIL_PATTERN.sub("xxx", text)
    text = re.sub(r"(?i)ttop5", "xxx", text)
    return text


def normalize_public_text(value: str | None) -> str:
    text = sanitize_public_text(value)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 \2", text)
    return text


def station_url(value: str | None) -> str:
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


def split_label_value(item: str) -> tuple[str, str]:
    for separator in ("：", ":"):
        if separator in item:
            left, right = item.split(separator, 1)
            return left.strip(), right.strip()
    return item.strip(), ""


def load_summary_intro() -> dict[str, Any]:
    summary_path = WORKSPACE_ROOT / "multiplier_audit_summary.md"
    summary_text = summary_path.read_text(encoding="utf-8-sig")
    lines = summary_text.splitlines()

    bullet_items: list[str] = []
    for line in lines[1:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            bullet_items.append(sanitize_public_text(line[2:].strip()))

    bullet_map: dict[str, str] = {}
    for item in bullet_items:
        label, value = split_label_value(item)
        if value:
            bullet_map[label] = value

    environment = bullet_map.get("环境说明", "")
    environment = environment.replace(f"（{HIGHLIGHT_PHRASE}）", HIGHLIGHT_PHRASE)

    supplemental_items = [
        item
        for item in bullet_items
        if not item.startswith(("采集时间", "环境说明", "采用倍率计算公式", "正式采用倍率", "综合评分权重"))
    ]

    adopted_rule = next((item for item in bullet_items if item.startswith("正式采用倍率")), "")

    return {
        "generated_at": bullet_map.get("采集时间", ""),
        "declaration": {
            "title": "特别声明",
            "subtitle": "以下结果基于同一批本机聚合日志、同一费用口径与同一评分权重做横向对比。",
            "items": supplemental_items,
            "environment": environment,
            "formula": bullet_map.get("采用倍率计算公式", ""),
            "adoptedMultiplierRule": adopted_rule,
            "scoring": bullet_map.get("综合评分权重", ""),
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

    return record


def load_announcements() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not PUBLIC_FETCH_DIR.exists():
        return grouped

    for path in sorted(PUBLIC_FETCH_DIR.glob("*_status.json")):
        station_key = path.stem.replace("_status", "")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

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


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    intro = load_summary_intro()
    rankings = {
        "work_hours": [ranking_row(row) for row in read_csv(WORKSPACE_ROOT / "composite_ranking_formal_workhours.csv")],
        "off_hours": [ranking_row(row) for row in read_csv(WORKSPACE_ROOT / "composite_ranking_formal_offhours.csv")],
        "all_hours": [ranking_row(row) for row in read_csv(WORKSPACE_ROOT / "composite_ranking_formal_all_hours.csv")],
    }
    quality_rows = [quality_row(row) for row in read_csv(WORKSPACE_ROOT / "quality_metrics.csv")]
    checklist_rows = read_csv(WORKSPACE_ROOT / "login_verification_checklist.csv")
    tier_rows = read_csv(WORKSPACE_ROOT / "multiplier_tiers.csv")
    announcements = load_announcements()

    stations: dict[str, dict[str, Any]] = {}
    station_urls: dict[str, set[str]] = {}

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

    for window_key, rows in rankings.items():
        for row in rows:
            station = ensure_station(
                stations,
                row["station"],
                label=row["label"],
                url=row["stationUrl"],
                station_type=row["stationType"],
            )
            station["rankings"][window_key] = row
            if row["stationUrl"]:
                station_urls.setdefault(row["station"], set()).add(row["stationUrl"])

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

    group_seen: dict[str, set[tuple[str, float]]] = {}
    recharge_seen: dict[str, set[tuple[Any, ...]]] = {}

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

        group_name = sanitize_public_text(row.get("group_name"))
        group_multiplier = parse_float(row.get("group_multiplier"))
        if group_name and group_multiplier is not None:
            group_bucket = group_seen.setdefault(station_key, set())
            group_key = (group_name, group_multiplier)
            if group_key not in group_bucket:
                station["groupMultipliers"].append(
                    {
                        "groupName": group_name,
                        "groupMultiplier": group_multiplier,
                    }
                )
                group_bucket.add(group_key)

        recharge_key = (
            sanitize_public_text(row.get("recharge_name")),
            row.get("billing_type", ""),
            row.get("rmb_amount", ""),
            row.get("usd_amount", ""),
            sanitize_public_text(row.get("recharge_location")),
            sanitize_public_text(row.get("expires_rule")),
        )
        recharge_bucket = recharge_seen.setdefault(station_key, set())
        if recharge_key not in recharge_bucket:
            billing_type = row.get("billing_type", "")
            station["rechargeTiers"].append(
                {
                    "rechargeName": sanitize_public_text(row.get("recharge_name")),
                    "billingType": billing_type,
                    "billingTypeLabel": BILLING_LABELS.get(billing_type, sanitize_public_text(billing_type or "未知")),
                    "rmbAmount": parse_float(row.get("rmb_amount")),
                    "usdAmount": parse_float(row.get("usd_amount")),
                    "rechargeLocation": sanitize_public_text(row.get("recharge_location")),
                    "expiresRule": sanitize_public_text(row.get("expires_rule")),
                }
            )
            recharge_bucket.add(recharge_key)

        note = normalize_public_text(row.get("notes"))
        if note and note not in station["tierNotes"]:
            station["tierNotes"].append(note)

        evidence_url = sanitize_public_text(row.get("evidence_url"))
        if evidence_url:
            station_urls.setdefault(station_key, set()).add(evidence_url)

    for station_key, rows in announcements.items():
        station = ensure_station(stations, station_key)
        station["announcements"] = rows

    station_list = sorted(
        stations.values(),
        key=lambda item: (
            item.get("rankings", {}).get("work_hours", {}).get("rank", 10**9),
            item.get("label", "").lower(),
        ),
    )

    for station in station_list:
        url_choices = dedupe_strings(list(station_urls.get(station["key"], set())) + [station.get("url", "")])
        station["url"] = choose_best_url(url_choices)

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

    output_path = DATA_DIR / "site-data.json"
    output_path.write_text(json.dumps(site_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "generated_at": intro["generated_at"],
                "output": str(output_path),
                "stations": len(station_list),
                "work_hours_ranked": len(rankings["work_hours"]),
                "off_hours_ranked": len(rankings["off_hours"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
