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
from urllib.parse import quote, urlparse, urlunparse


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
SOURCE_ROOTS = [APP_ROOT, WORKSPACE_ROOT]
DATA_DIR = APP_ROOT / "data"
SITE_DATA_PATH = DATA_DIR / "site-data.json"
PUBLIC_FETCH_DIR = Path(os.environ.get("PUBLIC_FETCH_DIR", DATA_DIR / "_public_fetch"))
AUDIT_RUNS_DIR = DATA_DIR / "_audit_runs"
PUBLIC_FETCH_DIRS = [PUBLIC_FETCH_DIR]
LIVE_AUTH_PROBE_DIR = WORKSPACE_ROOT / "tabbit-audit-profile"
STATION_PRICING_OVERRIDES_PATH = APP_ROOT / "config" / "station_pricing_overrides.json"
STATION_AUDIT_TARGETS_PATH = APP_ROOT / "config" / "station_audit_targets.json"
STATION_ALIASES_PATH = APP_ROOT / "config" / "station_aliases.json"

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
    "work_hours": {"key": "work_hours", "label": "工作时段", "range": "工作日09:00:00-18:00:00"},
    "off_hours": {"key": "off_hours", "label": "非工作时段", "range": "工作日18:00:01-次日08:59:59；周末全天"},
    "all_hours": {"key": "all_hours", "label": "全时段", "range": "00:00:00-23:59:59"},
}

HIGHLIGHT_PHRASE = "所以本排名更关注各中转站的服务下限。"
DISCLAIMER_EMPHASIS = "本排名无任何利益相关，仅供参考。"
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
PATH_PATTERN = re.compile(r"([A-Za-z]:\\Users\\)([^\\`]+)")
LOCALHOST_PATTERN = re.compile(r"^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$", re.IGNORECASE)
TOPUP_NAME_PATTERN = re.compile(r"wallet topup (\d+(?:\.\d+)?) RMB", re.IGNORECASE)
TOPUP_HTML_PATTERN = re.compile(
    r"(wallet\s*topup\s*(\d+(?:\.\d+)?)\s*RMB).*?(\d+(?:\.\d+)?)\s*(?:USD|\$)",
    re.IGNORECASE | re.DOTALL,
)
APP_CONFIG_PATTERN = re.compile(
    r"window\.__APP_CONFIG__\s*=\s*(\{.*?\})\s*;?\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
TRAILING_UI_SEGMENTS = {"console", "dashboard", "wallet", "keys", "purchase", "pricing", "plans", "api-keys"}
LOCALE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z]{2}(?:-[A-Za-z]{2})?$")


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
    return True


def is_public_station_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    if not host:
        return False
    return not LOCALHOST_PATTERN.fullmatch(host)


def normalize_public_text(value: Any) -> str:
    text = sanitize_public_text(value)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 \2", text)
    return text


def load_station_aliases() -> dict[str, str]:
    if not STATION_ALIASES_PATH.exists():
        return {}
    try:
        payload = json.loads(STATION_ALIASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    aliases: dict[str, str] = {}
    for raw_alias, raw_canonical in payload.items():
        alias = sanitize_public_text(raw_alias).strip()
        canonical = sanitize_public_text(raw_canonical).strip()
        if not alias or not canonical or alias == canonical:
            continue
        aliases[alias] = canonical
    return aliases


def canonical_station_key(station_key: Any, station_aliases: dict[str, str] | None = None) -> str:
    key = sanitize_public_text(station_key).strip()
    if not key:
        return ""
    aliases = station_aliases or {}
    seen: set[str] = set()
    while key in aliases and key not in seen:
        seen.add(key)
        next_key = sanitize_public_text(aliases[key]).strip()
        if not next_key or next_key == key:
            break
        key = next_key
    return key


def add_station_url(
    station_urls: dict[str, set[str]],
    station_key: Any,
    url: Any,
    station_aliases: dict[str, str] | None = None,
) -> None:
    canonical_key = canonical_station_key(station_key, station_aliases)
    if not canonical_key:
        return
    for normalized_url in extract_public_url_candidates(url):
        station_urls.setdefault(canonical_key, set()).add(normalized_url)


def add_exact_station_url(
    station_urls: dict[str, set[str]],
    station_key: Any,
    url: Any,
    station_aliases: dict[str, str] | None = None,
) -> None:
    canonical_key = canonical_station_key(station_key, station_aliases)
    normalized_url = sanitize_public_text(url)
    if canonical_key and normalized_url and is_public_station_url(normalized_url):
        station_urls.setdefault(canonical_key, set()).add(normalized_url)


def station_url(value: Any) -> str:
    urls = split_list(value)
    return sanitize_public_text(urls[0]) if urls else ""


def extract_public_url_candidates(value: Any) -> list[str]:
    text = sanitize_public_text(value)
    if not text:
        return []

    candidates: list[str] = []
    for raw_url in URL_PATTERN.findall(text):
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        root_url = f"{parsed.scheme}://{parsed.netloc}"
        candidates.append(raw_url.rstrip("/"))
        candidates.append(root_url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        while segments and segments[-1].lower() in TRAILING_UI_SEGMENTS:
            segments.pop()
        if len(segments) == 1 and LOCALE_SEGMENT_PATTERN.fullmatch(segments[0]):
            segments.pop()
        if segments:
            candidates.append(urlunparse((parsed.scheme, parsed.netloc, "/" + "/".join(segments), "", "", "")).rstrip("/"))
    return [candidate for candidate in dedupe_strings(candidates) if is_public_station_url(candidate)]


def collect_public_urls(value: Any) -> list[str]:
    if isinstance(value, dict):
        urls: list[str] = []
        for item in value.values():
            urls.extend(collect_public_urls(item))
        return dedupe_strings(urls)
    if isinstance(value, list):
        urls: list[str] = []
        for item in value:
            urls.extend(collect_public_urls(item))
        return dedupe_strings(urls)
    if isinstance(value, str):
        return extract_public_url_candidates(value)
    return []


def choose_best_url(urls: list[str]) -> str:
    expanded = dedupe_strings(
        candidate
        for url in urls
        for candidate in extract_public_url_candidates(url)
    )

    def score(url: str) -> tuple[int, int, str]:
        if not url:
            return (-10**6, 0, "")
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        base_score = 0
        path = parsed.path.rstrip("/")
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
        if path in {"", "/"}:
            base_score += 12
        else:
            base_score -= min(len(path), 10)
        return (base_score, -len(host), url)

    candidates = [candidate for candidate in expanded if candidate]
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
                "工作时段：周一至周五 09:00:00-18:00:00。",
                "非工作时段：工作日 18:00:01-次日 08:59:59；周末全天计入非工作时段。",
                "正式综合排名仅使用高置信度或人工核验的费用证据；0 倍率分组不参与排名。",
                "正式采用倍率优先使用 Codex 口径分组（`codex` / `openai` / `gpt` / `default`）中的最小非 0 倍率；若缺失，再回退到最低非 Claude 分组。",
                "sub2api 站点的公告、分组倍率、订阅和充值计划通常需要登录后查看；公开抓取只作为首页配置、文档链接和菜单项补充。",
                DISCLAIMER_EMPHASIS,
            ],
            "environment": "\n\n".join(
                [
                    "本次数据来自本人电脑上 Codex Manager 对多家中转站 Codex API Key 的聚合调用日志，使用场景为 Codex 接入开发。",
                    "由于所有请求均先经过 Codex Manager，再转发至各中转站，相比直连会天然增加一层延迟。",
                    f"费用口径统一按各站当前可核验的 Codex 口径最小非 0 分组倍率计算，`default` 分组视为 Codex 可用分组；若站点未显式区分 Codex，则回退到最低非 Claude 分组。该档位通常价格最低，但也往往延迟更高、稳定性更差，{HIGHLIGHT_PHRASE}",
                    "日志样本来自本人实际开发个人小项目期间的调用记录，网络环境为昆明广电宽带。以下排名仅反映本人使用时间点、当时账号状态与当时网络环境下的观测结果。",
                ]
            ),
            "coreItems": [
                "综合评分权重 = 正确响应率 40% + 响应时间 35% + 实际倍率 25%。",
                "实际倍率 = 分组倍率 × 实付人民币 ÷ 到账美元额度。",
                "正式采用倍率 = Codex 口径分组倍率（最小非 0 倍率） × 实付人民币 ÷ 到账美元额度。",
                "Codex 口径分组：分组名包含 `codex`、`openai`、`gpt`，或分组名为 `default`；若缺失，再回退到最低非 Claude 分组。",
                "正确响应定义：HTTP 2xx 且 error IS NULL；HTTP 200 但 error 非空也计为错误响应；因欠费、充值解锁、手机号验证等账户前置条件导致的错误样本，已从正确响应率统计中剔除。部分请求报错（如502）但能正常使用时，也计为错误响应。",
            ],
            "formula": "实际倍率 = 分组倍率 × 实付人民币 ÷ 到账美元额度。",
            "adoptedMultiplierRule": "正式采用倍率：优先取 Codex 口径分组中的最小非 0 实际倍率；若无明确 Codex/default 分组，再回退到最低非 Claude 分组。",
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


def earlier_timestamp_text(left: Any, right: Any) -> str:
    candidates = [str(value or "").strip() for value in (left, right) if str(value or "").strip()]
    if not candidates:
        return ""
    dated = [(parse_iso_datetime(value), value) for value in candidates]
    valid = [(dt, value) for dt, value in dated if dt is not None]
    if valid:
        return min(valid, key=lambda item: item[0])[1]
    return min(candidates)


def later_timestamp_text(left: Any, right: Any) -> str:
    candidates = [str(value or "").strip() for value in (left, right) if str(value or "").strip()]
    if not candidates:
        return ""
    dated = [(parse_iso_datetime(value), value) for value in candidates]
    valid = [(dt, value) for dt, value in dated if dt is not None]
    if valid:
        return max(valid, key=lambda item: item[0])[1]
    return max(candidates)


def weighted_average(left_value: Any, left_weight: int, right_value: Any, right_weight: int) -> float | None:
    left = parse_float(left_value)
    right = parse_float(right_value)
    if left is None and right is None:
        return None
    if left is None:
        return right
    if right is None:
        return left
    total_weight = max(left_weight, 0) + max(right_weight, 0)
    if total_weight <= 0:
        return (left + right) / 2
    return (left * max(left_weight, 0) + right * max(right_weight, 0)) / total_weight


def ranking_row_preference(row: dict[str, Any]) -> tuple[int, int, int]:
    return (
        1 if parse_bool(row.get("feeVerified")) else 0,
        parse_int(row.get("requests")),
        1 if sanitize_public_text(row.get("adoptedTier")) else 0,
    )


def quality_row_preference(row: dict[str, Any]) -> tuple[int, int]:
    return (
        parse_int(row.get("requestSamples")),
        1 if sanitize_public_text(row.get("platformGuess")) else 0,
    )


def merge_ranking_rows(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_requests = parse_int(existing.get("requests"))
    incoming_requests = parse_int(incoming.get("requests"))
    preferred = incoming if ranking_row_preference(incoming) > ranking_row_preference(existing) else existing
    merged = deepcopy(preferred)
    total_requests = existing_requests + incoming_requests
    total_correct = parse_int(existing.get("correct")) + parse_int(incoming.get("correct"))
    total_failures = parse_int(existing.get("failures")) + parse_int(incoming.get("failures"))
    total_http2xx = parse_int(existing.get("http2xx")) + parse_int(incoming.get("http2xx"))
    total_http200_with_error = parse_int(existing.get("http200WithError")) + parse_int(incoming.get("http200WithError"))
    merged["requests"] = total_requests
    merged["correct"] = total_correct
    merged["failures"] = total_failures
    merged["http2xx"] = total_http2xx
    merged["http200WithError"] = total_http200_with_error
    merged["correctRate"] = (total_correct / total_requests) if total_requests else 0.0
    merged["successScore"] = 100.0 * merged["correctRate"]
    merged["avgSeconds"] = weighted_average(existing.get("avgSeconds"), existing_requests, incoming.get("avgSeconds"), incoming_requests) or 0.0
    merged["medianSeconds"] = weighted_average(existing.get("medianSeconds"), existing_requests, incoming.get("medianSeconds"), incoming_requests)
    p95_values = [parse_float(existing.get("p95Seconds")), parse_float(incoming.get("p95Seconds"))]
    merged["p95Seconds"] = max((value for value in p95_values if value is not None), default=None)
    merged["latencyScore"] = weighted_average(existing.get("latencyScore"), existing_requests, incoming.get("latencyScore"), incoming_requests) or 0.0
    merged["firstAt"] = earlier_timestamp_text(existing.get("firstAt"), incoming.get("firstAt"))
    merged["lastAt"] = later_timestamp_text(existing.get("lastAt"), incoming.get("lastAt"))
    return merged


def merge_quality_rows(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_samples = parse_int(existing.get("requestSamples"))
    incoming_samples = parse_int(incoming.get("requestSamples"))
    preferred = incoming if quality_row_preference(incoming) > quality_row_preference(existing) else existing
    merged = deepcopy(preferred)
    total_samples = existing_samples + incoming_samples
    total_correct = parse_int(existing.get("correct")) + parse_int(incoming.get("correct"))
    total_failures = parse_int(existing.get("failures")) + parse_int(incoming.get("failures"))
    total_http2xx = parse_int(existing.get("http2xx")) + parse_int(incoming.get("http2xx"))
    total_http200_with_error = parse_int(existing.get("http200WithError")) + parse_int(incoming.get("http200WithError"))
    total_nonnull_error = parse_int(existing.get("nonnullError")) + parse_int(incoming.get("nonnullError"))
    total_excluded = parse_int(existing.get("excludedBillingErrors")) + parse_int(incoming.get("excludedBillingErrors"))
    merged["requestSamples"] = total_samples
    merged["correct"] = total_correct
    merged["failures"] = total_failures
    merged["correctRate"] = (total_correct / total_samples) if total_samples else 0.0
    merged["http2xx"] = total_http2xx
    merged["http200WithError"] = total_http200_with_error
    merged["nonnullError"] = total_nonnull_error
    merged["excludedBillingErrors"] = total_excluded
    merged["avgSeconds"] = weighted_average(existing.get("avgSeconds"), existing_samples, incoming.get("avgSeconds"), incoming_samples)
    merged["medianSeconds"] = weighted_average(existing.get("medianSeconds"), existing_samples, incoming.get("medianSeconds"), incoming_samples)
    p95_values = [parse_float(existing.get("p95Seconds")), parse_float(incoming.get("p95Seconds"))]
    merged["p95Seconds"] = max((value for value in p95_values if value is not None), default=None)
    merged["avgFirstResponseSeconds"] = weighted_average(
        existing.get("avgFirstResponseSeconds"),
        existing_samples,
        incoming.get("avgFirstResponseSeconds"),
        incoming_samples,
    )
    merged["firstAt"] = earlier_timestamp_text(existing.get("firstAt"), incoming.get("firstAt"))
    merged["lastAt"] = later_timestamp_text(existing.get("lastAt"), incoming.get("lastAt"))
    return merged


def merge_ranking_rows_by_station(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    merged_by_station: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    merged_any = False
    for row in rows:
        station_key = canonical_station_key(row.get("station"))
        if not station_key:
            continue
        next_row = deepcopy(row)
        next_row["station"] = station_key
        existing = merged_by_station.get(station_key)
        if existing is None:
            merged_by_station[station_key] = next_row
            order.append(station_key)
            continue
        merged_by_station[station_key] = merge_ranking_rows(existing, next_row)
        merged_any = True
    return [merged_by_station[station_key] for station_key in order], merged_any


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


def ensure_station(
    container: dict[str, dict[str, Any]],
    station_key: str,
    *,
    station_aliases: dict[str, str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    raw_station_key = sanitize_public_text(station_key).strip()
    station_key = canonical_station_key(raw_station_key, station_aliases)
    station_type = overrides.get("station_type") or "unknown_pending"
    record = container.setdefault(
        station_key,
        {
            "key": station_key,
            "label": sanitize_public_text(overrides.get("label")) if raw_station_key == station_key else station_key,
            "url": sanitize_public_text(overrides.get("url")) if raw_station_key == station_key else "",
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

    if raw_station_key == station_key and overrides.get("label"):
        record["label"] = sanitize_public_text(overrides["label"])
    if raw_station_key == station_key and overrides.get("url"):
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


def load_status_payloads(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    fetch_dirs = [path for path in PUBLIC_FETCH_DIRS if path.exists()]
    if not fetch_dirs:
        return grouped

    for fetch_dir in fetch_dirs:
        for path in sorted(fetch_dir.glob("*_status.json")):
            station_key = canonical_station_key(path.stem.replace("_status", ""), station_aliases)
            if not is_public_station_key(station_key):
                continue
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


def load_live_auth_probes(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    if not LIVE_AUTH_PROBE_DIR.exists():
        return grouped
    for path in sorted(LIVE_AUTH_PROBE_DIR.glob("*-live-auth-probe.json")):
        station_key = canonical_station_key(path.name.removesuffix("-live-auth-probe.json"), station_aliases)
        if not is_public_station_key(station_key):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload["_probePath"] = str(path)
            grouped[station_key] = payload
    return grouped


def probe_location(probe: dict[str, Any]) -> str:
    return sanitize_public_text(probe.get("location") or probe.get("url") or "")


def probe_source_url(probe: dict[str, Any], api_path: str) -> str:
    location = probe_location(probe)
    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}{api_path}"
    return location


def find_probe_result(probe: dict[str, Any], api_path: str) -> dict[str, Any] | None:
    results = probe.get("results")
    if not isinstance(results, dict):
        return None
    direct = results.get(api_path)
    if isinstance(direct, dict):
        return direct
    for bucket in results.values():
        if not isinstance(bucket, dict):
            continue
        nested = bucket.get(api_path)
        if isinstance(nested, dict):
            return nested
    return None


def probe_result_body_from_entry(entry: dict[str, Any] | None) -> Any:
    if not isinstance(entry, dict):
        return None
    return entry.get("body")


def probe_result_data_from_entry(entry: dict[str, Any] | None) -> Any:
    body = probe_result_body_from_entry(entry)
    if isinstance(body, dict):
        return body.get("data")
    return None


def looks_like_notice_text(value: str) -> bool:
    text = normalize_public_text(value)
    if not text:
        return False
    lowered = text[:300].lower()
    if lowered.startswith("<!doctype") or lowered.startswith("<html") or "<script" in lowered:
        return False
    return True


def extract_collection(raw: Any, *, allow_text_item: bool = False) -> tuple[list[Any], bool]:
    if isinstance(raw, list):
        return raw, True
    if allow_text_item and isinstance(raw, str) and looks_like_notice_text(raw):
        return [{"content": raw}], True
    if not isinstance(raw, dict):
        return [], False
    for key in ("announcements", "items", "list", "records", "rows", "data"):
        if key not in raw:
            continue
        rows, found = extract_collection(raw.get(key), allow_text_item=allow_text_item)
        if found:
            return rows, True
    return [], False


def normalize_live_announcement(station_key: str, item: dict[str, Any], index: int, source_url: str) -> dict[str, Any] | None:
    title = normalize_public_text(item.get("title") or item.get("name") or item.get("subject"))
    content = normalize_public_text(
        item.get("content")
        or item.get("message")
        or item.get("body")
        or item.get("description")
        or item.get("text")
        or title
    )
    if not content:
        return None
    published_at = sanitize_public_text(
        item.get("publishDate")
        or item.get("publishedAt")
        or item.get("published_at")
        or item.get("createdAt")
        or item.get("created_at")
        or item.get("updatedAt")
        or item.get("updated_at")
    )
    extra = normalize_public_text(item.get("extra") or item.get("summary") or "")
    if title and title != content:
        extra = title if not extra else f"{title} | {extra}"
    return {
        "id": str(item.get("id") or item.get("uuid") or f"{station_key}-live-{index}"),
        "publishedAt": published_at,
        "type": sanitize_public_text(item.get("type") or item.get("category") or item.get("level") or "login_probe"),
        "extra": extra,
        "content": content,
        "sourceUrl": source_url,
    }


def live_probe_announcements_and_status(station_key: str, probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    first_failure: dict[str, str] | None = None
    first_empty: dict[str, str] | None = None
    for api_path in ("/api/v1/announcements", "/api/announcements", "/api/status", "/api/notice", "/api/notices"):
        entry = find_probe_result(probe, api_path)
        if entry is None:
            continue
        status = int(entry.get("status") or 0)
        ok = bool(entry.get("ok"))
        body = probe_result_body_from_entry(entry)
        rows, found = extract_collection(body, allow_text_item="notice" in api_path.lower())
        source_url = probe_source_url(probe, api_path)
        if status and not ok and status >= 400:
            if entry_is_blocked(entry):
                return [], {
                    "status": "blocked",
                    "source": source_url,
                    "message": "登录态公告接口被验证码或风控阻断",
                }
            if first_failure is None:
                first_failure = {
                    "status": "failed",
                    "source": source_url,
                    "message": f"登录态公告接口返回 HTTP {status}",
                }
            continue
            return [], {
                "status": "failed",
                "source": source_url,
                "message": f"登录态公告接口返回 HTTP {status}",
            }
        if not found:
            if first_empty is None:
                first_empty = {
                    "status": "empty",
                    "source": source_url,
                    "message": "公告接口已访问，但响应中没有标准公告列表",
                }
            continue
            return [], {
                "status": "empty",
                "source": source_url,
                "message": "登录态公告接口已访问，但响应中没有标准公告列表",
            }
        announcements = [
            row
            for index, item in enumerate(rows, start=1)
            if isinstance(item, dict)
            for row in [normalize_live_announcement(station_key, item, index, source_url)]
            if row
        ]
        if announcements:
            return announcements, {
                "status": "captured",
                "source": source_url,
                "message": f"登录态公告接口抓取到 {len(announcements)} 条",
            }
        if first_empty is None:
            first_empty = {
                "status": "empty",
                "source": source_url,
                "message": "登录态公告接口返回空列表",
            }
    if first_empty is not None:
        return [], first_empty
    if first_failure is not None:
        return [], first_failure
    return [], {
        "status": "missing",
        "source": sanitize_public_text(probe.get("_probePath") or probe_location(probe)),
        "message": "live auth probe 尚未包含公告接口",
    }


def entry_is_blocked(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    if int(entry.get("status") or 0) in {403, 429}:
        return True
    text = json.dumps(entry.get("body", entry), ensure_ascii=False).lower()
    return any(marker in text for marker in ("turnstile", "captcha", "验证码", "人机验证", "风控"))


def live_probe_group_rows(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    entry = find_probe_result(probe, "/api/v1/groups/available")
    data = probe_result_data_from_entry(entry)
    rows = data if isinstance(data, list) else []
    groups: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "active").strip().lower() not in {"", "active"}:
            continue
        group = normalize_group_row(
            {
                "groupName": item.get("name") or item.get("groupName") or item.get("group_name"),
                "groupMultiplier": item.get("rate_multiplier")
                if "rate_multiplier" in item
                else item.get("groupMultiplier", item.get("group_multiplier", item.get("ratio"))),
            }
        )
        if group:
            groups.append(group)
    source = probe_source_url(probe, "/api/v1/groups/available")
    if groups:
        return groups, {"status": "captured", "source": source, "message": f"登录态分组接口抓取到 {len(groups)} 条"}
    if entry is not None:
        if entry_is_blocked(entry):
            return [], {"status": "blocked", "source": source, "message": "登录态分组接口被验证码或风控阻断"}
        status = int(entry.get("status") or 0)
        message = f"登录态分组接口返回 HTTP {status}" if status >= 400 else "登录态分组接口返回空列表"
        return [], {"status": "empty" if status < 400 else "failed", "source": source, "message": message}
    return [], {"status": "missing", "source": sanitize_public_text(probe.get("_probePath") or probe_location(probe)), "message": "live auth probe 尚未包含分组接口"}


def duration_unit_to_billing_type(unit: Any) -> str:
    text = str(unit or "").strip().lower()
    if text in {"month", "monthly"}:
        return "monthly"
    if text in {"week", "weekly"}:
        return "weekly"
    if text in {"day", "daily"}:
        return "daily"
    if text in {"year", "yearly"}:
        return "monthly"
    return "permanent"


def convert_quota_to_usd(quota_value: Any) -> float | None:
    raw = parse_float(quota_value)
    if raw is None:
        return None
    return raw / 500000.0


def live_probe_recharge_rows(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    tiers: list[dict[str, Any]] = []
    plan_entry = find_probe_result(probe, "/api/v1/payment/plans")
    plan_rows, _found_plans = extract_collection(probe_result_data_from_entry(plan_entry))
    for item in plan_rows:
        if not isinstance(item, dict):
            continue
        plan = item.get("plan") if isinstance(item.get("plan"), dict) else item
        title = sanitize_public_text(plan.get("title") or plan.get("name") or "subscription plan")
        price = parse_float(plan.get("price") or plan.get("amount") or plan.get("rmbAmount") or plan.get("rmb_amount"))
        usd_amount = parse_float(plan.get("usdAmount") or plan.get("usd_amount") or plan.get("usd"))
        if usd_amount is None:
            usd_amount = convert_quota_to_usd(plan.get("total_amount") or plan.get("quota"))
        row = normalize_recharge_row(
            {
                "rechargeName": title,
                "billingType": duration_unit_to_billing_type(plan.get("duration_unit") or plan.get("billing_type")),
                "rmbAmount": price,
                "usdAmount": usd_amount,
                "rechargeLocation": "login probe payment plans API",
                "expiresRule": sanitize_public_text(plan.get("subtitle") or plan.get("description") or plan.get("desc")),
            }
        )
        if row:
            tiers.append(row)

    config_entry = find_probe_result(probe, "/api/v1/payment/config")
    checkout_entry = find_probe_result(probe, "/api/v1/payment/checkout-info")
    payment_config = probe_result_data_from_entry(config_entry)
    checkout_info = probe_result_data_from_entry(checkout_entry)
    payment_config = payment_config if isinstance(payment_config, dict) else {}
    checkout_info = checkout_info if isinstance(checkout_info, dict) else {}
    recharge_multiplier = (
        parse_float(checkout_info.get("balance_recharge_multiplier"))
        or parse_float(payment_config.get("balance_recharge_multiplier"))
        or 0.0
    )
    balance_disabled = bool(checkout_info.get("balance_disabled", payment_config.get("balance_disabled")))
    quick_amounts = probe.get("quick_amounts") if isinstance(probe.get("quick_amounts"), list) else []
    if recharge_multiplier > 0 and not balance_disabled and quick_amounts:
        methods = checkout_info.get("methods") if isinstance(checkout_info.get("methods"), dict) else {}
        method_text = ", ".join(sorted(str(name) for name in methods)) or "login probe"
        fee_rate = parse_float(checkout_info.get("recharge_fee_rate") or payment_config.get("recharge_fee_rate")) or 0.0
        for raw_amount in quick_amounts:
            rmb_amount = parse_float(raw_amount)
            if rmb_amount is None or rmb_amount <= 0:
                continue
            paid_rmb = rmb_amount * (1 + fee_rate / 100)
            usd_amount = rmb_amount * recharge_multiplier
            row = normalize_recharge_row(
                {
                    "rechargeName": f"wallet topup {format_plain_number(rmb_amount)} RMB",
                    "billingType": "permanent",
                    "rmbAmount": paid_rmb,
                    "usdAmount": usd_amount,
                    "rechargeLocation": f"login probe payment config API ({method_text})",
                    "expiresRule": f"No expiry stated; balance top-up; recharge fee {format_plain_number(fee_rate)}%",
                }
            )
            if row:
                tiers.append(row)

    source = probe_source_url(probe, "/api/v1/payment/checkout-info")
    if tiers:
        return tiers, {"status": "captured", "source": source, "message": f"登录态充值接口抓取到 {len(tiers)} 条"}
    payment_entries = [
        entry
        for entry in (config_entry, checkout_entry, plan_entry)
        if isinstance(entry, dict)
    ]
    payment_statuses = [
        int(entry.get("status") or 0)
        for entry in payment_entries
        if int(entry.get("status") or 0) > 0
    ]
    if payment_statuses and all(status >= 400 for status in payment_statuses):
        if any(entry_is_blocked(entry) for entry in payment_entries):
            return [], {
                "status": "blocked",
                "source": source,
                "message": "登录态支付接口被验证码或风控阻断",
            }
        return [], {
            "status": "failed",
            "source": source,
            "message": f"login probe payment APIs returned HTTP {payment_statuses[0]}",
        }
    if config_entry is not None or checkout_entry is not None or plan_entry is not None:
        return [], {"status": "empty", "source": source, "message": "登录态支付接口可访问，但没有可结构化的充值档位"}
    return [], {"status": "missing", "source": sanitize_public_text(probe.get("_probePath") or probe_location(probe)), "message": "live auth probe 尚未包含支付接口"}


def merge_announcements(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in existing + incoming:
        key = (
            str(item.get("id") or ""),
            str(item.get("publishedAt") or ""),
            str(item.get("content") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def normalize_live_probe_status(status: dict[str, str]) -> dict[str, str]:
    if not isinstance(status, dict):
        return status
    message = str(status.get("message") or "")
    if status.get("status") == "failed" and "HTTP 401" in message:
        normalized = dict(status)
        normalized["status"] = "login_required"
        normalized["message"] = "需要登录或权限不足 (HTTP 401)"
        return normalized
    if status.get("status") == "failed" and any(marker in message.lower() for marker in ("turnstile", "captcha", "验证码", "人机验证", "风控")):
        normalized = dict(status)
        normalized["status"] = "blocked"
        normalized["message"] = "接口被验证码或风控阻断"
        return normalized
    return status


def load_live_probe_snapshots(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for station_key, probe in load_live_auth_probes(station_aliases).items():
        announcements, announcement_status = live_probe_announcements_and_status(station_key, probe)
        groups, group_status = live_probe_group_rows(probe)
        recharges, recharge_status = live_probe_recharge_rows(probe)
        announcement_status = normalize_live_probe_status(announcement_status)
        group_status = normalize_live_probe_status(group_status)
        recharge_status = normalize_live_probe_status(recharge_status)
        snapshots[station_key] = {
            "announcements": announcements,
            "groupMultipliers": groups,
            "rechargeTiers": recharges,
            "evidenceStatus": {
                "announcements": announcement_status,
                "groupMultipliers": group_status,
                "rechargeTiers": recharge_status,
            },
            "sourceUrl": probe_location(probe),
        }
    return snapshots


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


def load_base_site_snapshot(
    station_aliases: dict[str, str] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, set[str]]]:
    existing = read_existing_site_data()
    rankings = empty_rankings()
    for window_key in TIME_WINDOWS:
        rows = []
        for raw_row in existing.get("rankings", {}).get(window_key, []):
            row = deepcopy(raw_row)
            row["station"] = canonical_station_key(row.get("station"), station_aliases)
            rows.append(row)
        rankings[window_key], _ = merge_ranking_rows_by_station(rows)

    stations: dict[str, dict[str, Any]] = {}
    station_urls: dict[str, set[str]] = {}
    for raw_station in existing.get("stations", []):
        raw_station_key = sanitize_public_text(raw_station.get("key")).strip()
        station_key = canonical_station_key(raw_station.get("key"), station_aliases)
        if not station_key:
            continue
        station = ensure_station(
            stations,
            raw_station_key,
            station_aliases=station_aliases,
            label=raw_station.get("label", ""),
            url=raw_station.get("url", ""),
            station_type=raw_station.get("stationType", ""),
            platform_guess=raw_station.get("platformGuess", ""),
        )
        raw_label = sanitize_public_text(raw_station.get("label"))
        raw_url = sanitize_public_text(raw_station.get("url"))
        raw_station_type = raw_station.get("stationType", "")
        raw_station_type_label = sanitize_public_text(raw_station.get("stationTypeLabel"))
        raw_station_type_short = sanitize_public_text(raw_station.get("stationTypeShortLabel"))
        raw_platform = sanitize_public_text(raw_station.get("platformGuess"))
        if raw_label and (raw_station_key == station_key or station.get("label") == station_key):
            station["label"] = raw_label
        if raw_url and (raw_station_key == station_key or not station.get("url")):
            station["url"] = raw_url
        if raw_station_type and (raw_station_key == station_key or station.get("stationType") == "unknown_pending"):
            station["stationType"] = raw_station_type
            station["stationTypeLabel"] = raw_station_type_label or station["stationTypeLabel"]
            station["stationTypeShortLabel"] = raw_station_type_short or station["stationTypeShortLabel"]
        if raw_platform and (raw_station_key == station_key or not station.get("platformGuess")):
            station["platformGuess"] = raw_platform
        station["verifiedTierCount"] = max(parse_int(station.get("verifiedTierCount")), parse_int(raw_station.get("verifiedTierCount")))
        for group in raw_station.get("groupMultipliers", []):
            if isinstance(group, dict):
                normalized_group = normalize_group_row(group)
                if normalized_group:
                    append_group_row(station, normalized_group)
        for tier in raw_station.get("rechargeTiers", []):
            if isinstance(tier, dict):
                normalized_tier = normalize_recharge_row(tier)
                if normalized_tier:
                    append_recharge_row(station, normalized_tier)
        for note in raw_station.get("tierNotes", []):
            normalized_note = normalize_public_text(note)
            if normalized_note and normalized_note not in station["tierNotes"]:
                station["tierNotes"].append(normalized_note)
        station["announcements"] = merge_announcements(station.get("announcements", []), raw_station.get("announcements", []))
        for window_key, quality_payload in (raw_station.get("quality") or {}).items():
            if not isinstance(quality_payload, dict):
                continue
            existing_quality = station["quality"].get(window_key)
            station["quality"][window_key] = merge_quality_rows(existing_quality, quality_payload) if isinstance(existing_quality, dict) else deepcopy(quality_payload)
        if raw_station.get("audits") and not station.get("audits"):
            station["audits"] = deepcopy(raw_station["audits"])
        if station.get("url"):
            add_station_url(station_urls, station_key, station["url"], station_aliases)
        for announcement in station.get("announcements", []):
            source_url = sanitize_public_text(announcement.get("sourceUrl"))
            if source_url:
                add_station_url(station_urls, station_key, source_url, station_aliases)

    sync_station_rankings_from_rankings(stations, rankings, station_aliases=station_aliases)
    return rankings, stations, station_urls


def reset_station_tiers(stations: dict[str, dict[str, Any]]) -> None:
    for station in stations.values():
        station["verifiedTierCount"] = 0
        station["groupMultipliers"] = []
        station["rechargeTiers"] = []
        station["tierNotes"] = []


def sync_station_rankings_from_rankings(
    stations: dict[str, dict[str, Any]],
    rankings: dict[str, list[dict[str, Any]]],
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    for station in stations.values():
        station["rankings"] = {}

    for window_key, rows in rankings.items():
        for row in rows:
            station = ensure_station(
                stations,
                row.get("station", ""),
                station_aliases=station_aliases,
                label=row.get("label", ""),
                url=row.get("stationUrl", ""),
                station_type=row.get("stationType", ""),
            )
            station["rankings"][window_key] = row


def sync_station_metadata_into_rows(
    stations: dict[str, dict[str, Any]],
    rankings: dict[str, list[dict[str, Any]]],
) -> None:
    for rows in rankings.values():
        for row in rows:
            station = stations.get(str(row.get("station") or "").strip())
            if not station:
                continue
            row["label"] = sanitize_public_text(station.get("label"))
            row["stationUrl"] = sanitize_public_text(station.get("url"))
            row["stationType"] = station.get("stationType", "")
            row["stationTypeLabel"] = station.get("stationTypeLabel", "")
            row["stationTypeShortLabel"] = station.get("stationTypeShortLabel", "")

    for station in stations.values():
        for row in station.get("quality", {}).values():
            if not isinstance(row, dict):
                continue
            row["station"] = station["key"]
            row["label"] = sanitize_public_text(station.get("label"))
            row["platformGuess"] = sanitize_public_text(station.get("platformGuess"))


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
        "stationTypeHint": "",
    }


def truthy_public_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def parse_app_config_from_html(content: str) -> dict[str, Any] | None:
    match = APP_CONFIG_PATTERN.search(content)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def infer_station_type_from_app_config(app_config: dict[str, Any]) -> str:
    payment_enabled = truthy_public_flag(app_config.get("payment_enabled"))
    subscription_enabled = truthy_public_flag(app_config.get("purchase_subscription_enabled"))
    if payment_enabled and subscription_enabled:
        return "mixed"
    if payment_enabled:
        return "non_subscription"
    if subscription_enabled:
        return "subscription"
    return ""


def parse_public_pricing_html(content: str) -> dict[str, Any]:
    recharge_tiers: list[dict[str, Any]] = []
    tier_notes: list[str] = []
    source_url = ""
    station_type_hint = ""

    app_config = parse_app_config_from_html(content)
    if app_config:
        station_type_hint = infer_station_type_from_app_config(app_config)
        source_url = sanitize_public_text(app_config.get("api_base_url") or "")
        if truthy_public_flag(app_config.get("payment_enabled")):
            recharge_url = sanitize_public_text(
                app_config.get("balance_low_notify_recharge_url") or app_config.get("purchase_subscription_url")
            )
            note = "公开配置显示已开启余额充值，但具体档位金额仍需登录/核验。"
            if recharge_url:
                note = f"{note} 充值入口：{recharge_url}"
            tier_notes.append(note)
        if truthy_public_flag(app_config.get("purchase_subscription_enabled")):
            tier_notes.append("公开配置显示已开启订阅购买，但具体套餐仍需登录/核验。")

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
        "tierNotes": tier_notes,
        "sourceUrl": source_url,
        "stationTypeHint": station_type_hint,
    }


def load_public_pricing_snapshots(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    fetch_dirs = [path for path in PUBLIC_FETCH_DIRS if path.exists()]
    if not fetch_dirs:
        return grouped

    for fetch_dir in fetch_dirs:
        for path in sorted(fetch_dir.glob("*_pricing.*")):
            station_key = canonical_station_key(path.stem.replace("_pricing", ""), station_aliases)
            if not is_public_station_key(station_key):
                continue
            parsed = {
                "groupMultipliers": [],
                "rechargeTiers": [],
                "tierNotes": [],
                "sourceUrl": "",
                "stationTypeHint": "",
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

            if (
                not parsed["groupMultipliers"]
                and not parsed["rechargeTiers"]
                and not parsed["tierNotes"]
                and not parsed.get("stationTypeHint")
            ):
                continue

            bucket = grouped.setdefault(
                station_key,
                {
                    "groupMultipliers": [],
                    "rechargeTiers": [],
                    "tierNotes": [],
                    "sourceUrl": parsed["sourceUrl"],
                    "stationTypeHint": "",
                },
            )
            if parsed["sourceUrl"]:
                bucket["sourceUrl"] = parsed["sourceUrl"]
            if parsed.get("stationTypeHint") and not bucket.get("stationTypeHint"):
                bucket["stationTypeHint"] = parsed["stationTypeHint"]
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


def load_public_probe_snapshots(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    fetch_dirs = [path for path in PUBLIC_FETCH_DIRS if path.exists()]
    if not fetch_dirs:
        return grouped

    for fetch_dir in fetch_dirs:
        probe_paths = sorted(fetch_dir.glob("*_public_probe.json")) + sorted(fetch_dir.glob("*_api_base_probe.json"))
        for path in probe_paths:
            station_key = canonical_station_key(
                path.stem.replace("_public_probe", "").replace("_api_base_probe", ""),
                station_aliases,
            )
            if not is_public_station_key(station_key):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            bucket = grouped.setdefault(
                station_key,
                {
                    "urls": [],
                    "evidenceStatus": {},
                },
            )
            bucket["urls"].extend(collect_public_urls(payload))
            source = sanitize_public_text(payload.get("baseUrl") or payload.get("base_url") or payload.get("location"))
            if source:
                bucket["evidenceStatus"]["publicProbe"] = {
                    "status": "captured",
                    "source": source,
                    "message": "公开探针已归档，可用于主站地址与证据合并。",
                }
    return grouped


def load_station_audit_targets(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
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
        station_key = canonical_station_key(item.get("station"), station_aliases)
        if not is_public_station_key(station_key):
            continue
        models = [sanitize_public_text(model) for model in item.get("models", []) if sanitize_public_text(model)]
        default_model = sanitize_public_text(item.get("defaultModel")) or (models[0] if models else "")
        result[station_key] = {
            "defaultModel": default_model,
            "availableModels": models,
        }
    return result


def load_latest_station_audits(station_aliases: dict[str, str] | None = None) -> dict[str, list[dict[str, Any]]]:
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
        station_key = canonical_station_key(parts[0], station_aliases)
        if not is_public_station_key(station_key):
            continue
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


def load_station_audit_history(
    station_records: dict[str, dict[str, Any]] | None = None,
    station_aliases: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    station_records = station_records or {}
    rows: list[dict[str, Any]] = []
    if not AUDIT_RUNS_DIR.exists():
        return rows

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
        station_key, model_dir, run_id = parts[:3]
        canonical_key = canonical_station_key(station_key, station_aliases)
        if not is_public_station_key(station_key):
            continue

        station = station_records.get(canonical_key, {})
        row = dict(summary)
        row.update(
            {
                "stationKey": canonical_key,
                "stationLabel": sanitize_public_text(station.get("label")) or audit_station_label_from_base_url(summary.get("auditedBaseUrl"), canonical_key),
                "stationUrl": sanitize_public_text(station.get("url")) or sanitize_public_text(summary.get("auditedBaseUrl")),
                "runId": run_id,
                "reportUrl": (
                    f"/api/audit-report?station={quote(station_key)}"
                    f"&model={quote(model_dir)}"
                    f"&run={quote(run_id)}"
                ),
            }
        )
        rows.append(row)

    rows.sort(key=lambda item: audit_sort_datetime(item.get("executedAt")), reverse=True)
    return rows


def apply_audit_only_station_records(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    latest_audits: dict[str, list[dict[str, Any]]],
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    for station_key, audit_rows in latest_audits.items():
        if not audit_rows:
            continue

        audited_base_url = sanitize_public_text(audit_rows[0].get("auditedBaseUrl"))
        if station_key in stations:
            station = ensure_station(stations, station_key, station_aliases=station_aliases)
            if audited_base_url and not station.get("url"):
                station["url"] = audited_base_url
        else:
            station = ensure_station(
                stations,
                station_key,
                station_aliases=station_aliases,
                label=audit_station_label_from_base_url(audited_base_url, station_key),
                url=audited_base_url,
            )

        if audited_base_url:
            add_exact_station_url(station_urls, station_key, audited_base_url, station_aliases)


def load_station_pricing_overrides(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    if not STATION_PRICING_OVERRIDES_PATH.exists():
        return {}
    payload = json.loads(STATION_PRICING_OVERRIDES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    overrides: dict[str, dict[str, Any]] = {}
    for station_key, value in payload.items():
        if not isinstance(value, dict):
            continue
        canonical_key = canonical_station_key(station_key, station_aliases)
        if not canonical_key:
            continue
        overrides[canonical_key] = value
    return overrides


def apply_public_pricing_snapshots(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    pricing_snapshots: dict[str, dict[str, Any]],
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    for station_key, snapshot in pricing_snapshots.items():
        station = ensure_station(stations, station_key, station_aliases=station_aliases)
        station_type_hint = sanitize_public_text(snapshot.get("stationTypeHint"))
        if (
            station.get("stationType") == "unknown_pending"
            and station_type_hint in FULL_TYPE_LABELS
            and station_type_hint != "unknown_pending"
        ):
            station["stationType"] = station_type_hint
            station["stationTypeLabel"] = FULL_TYPE_LABELS.get(station_type_hint, station_type_hint)
            station["stationTypeShortLabel"] = SHORT_TYPE_LABELS.get(station_type_hint, station_type_hint)
        source_url = sanitize_public_text(snapshot.get("sourceUrl"))
        if source_url:
            add_station_url(station_urls, station_key, source_url, station_aliases)
        for group in snapshot.get("groupMultipliers", []):
            append_group_row(station, group)
        for tier in snapshot.get("rechargeTiers", []):
            append_recharge_row(station, tier)
        for note in snapshot.get("tierNotes", []):
            normalized = normalize_public_text(note)
            if normalized and normalized not in station["tierNotes"]:
                station["tierNotes"].append(normalized)


def apply_live_probe_snapshots(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    live_snapshots: dict[str, dict[str, Any]],
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    for station_key, snapshot in live_snapshots.items():
        station = ensure_station(stations, station_key, station_aliases=station_aliases)
        source_url = sanitize_public_text(snapshot.get("sourceUrl"))
        if source_url:
            add_station_url(station_urls, station_key, source_url, station_aliases)
        for group in snapshot.get("groupMultipliers", []):
            append_group_row(station, group)
        for tier in snapshot.get("rechargeTiers", []):
            append_recharge_row(station, tier)
        if snapshot.get("announcements"):
            station["announcements"] = merge_announcements(station.get("announcements", []), snapshot["announcements"])


def evidence_item(
    *,
    key: str,
    label: str,
    count: int,
    fallback_status: str,
    fallback_message: str,
    live_status: dict[str, str] | None,
) -> dict[str, Any]:
    if count > 0:
        return {
            "key": key,
            "label": label,
            "count": count,
            "status": "captured",
            "statusLabel": "已抓取",
            "message": f"已归档 {count} 条，可在本详情页查看。",
            "source": sanitize_public_text((live_status or {}).get("source")),
        }

    status = sanitize_public_text((live_status or {}).get("status")) or fallback_status
    message = normalize_public_text((live_status or {}).get("message")) or fallback_message
    source = sanitize_public_text((live_status or {}).get("source"))
    status_labels = {
        "captured": "已抓取",
        "empty": "接口返回空",
        "failed": "抓取失败",
        "missing": "未抓到",
        "login_required": "需要登录",
        "blocked": "风控阻断",
        "public_missing": "未发现公开接口",
    }
    return {
        "key": key,
        "label": label,
        "count": 0,
        "status": status,
        "statusLabel": status_labels.get(status, status or "未抓到"),
        "message": message,
        "source": source,
    }


def build_station_evidence_status(station: dict[str, Any], live_snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    live_statuses = (live_snapshot or {}).get("evidenceStatus") if isinstance(live_snapshot, dict) else {}
    live_statuses = live_statuses if isinstance(live_statuses, dict) else {}
    platform = str(station.get("platformGuess") or "").strip().lower()
    sub2api_login_message = "sub2api 的该类接口通常需要登录态；当前公开快照或已归档 probe 没有可用结构化数据。"
    announcement_message = (
        "sub2api 公告通常位于登录态 /api/v1/announcements；当前没有抓到可展示内容。"
        if platform == "sub2api"
        else "未发现标准公开公告接口或接口未返回公告内容。"
    )
    evidence_rows = [
        evidence_item(
            key="groupMultipliers",
            label="分组倍率",
            count=len(station.get("groupMultipliers", [])),
            fallback_status="login_required" if platform == "sub2api" else "missing",
            fallback_message=sub2api_login_message if platform == "sub2api" else "当前未抓到结构化分组倍率。",
            live_status=live_statuses.get("groupMultipliers") if isinstance(live_statuses.get("groupMultipliers"), dict) else None,
        ),
        evidence_item(
            key="rechargeTiers",
            label="充值档位",
            count=len(station.get("rechargeTiers", [])),
            fallback_status="login_required" if platform == "sub2api" else "missing",
            fallback_message=sub2api_login_message if platform == "sub2api" else "当前未抓到结构化充值档位。",
            live_status=live_statuses.get("rechargeTiers") if isinstance(live_statuses.get("rechargeTiers"), dict) else None,
        ),
        evidence_item(
            key="announcements",
            label="公告",
            count=len(station.get("announcements", [])),
            fallback_status="login_required" if platform == "sub2api" else "public_missing",
            fallback_message=announcement_message,
            live_status=live_statuses.get("announcements") if isinstance(live_statuses.get("announcements"), dict) else None,
        ),
    ]
    if station.get("_publicProbeCaptured") or isinstance(live_statuses.get("publicProbe"), dict):
        evidence_rows.append(
            evidence_item(
                key="publicProbe",
                label="公开探针",
                count=1 if station.get("_publicProbeCaptured") else 0,
                fallback_status="missing",
                fallback_message="未抓到公开探针证据。",
                live_status=live_statuses.get("publicProbe") if isinstance(live_statuses.get("publicProbe"), dict) else None,
            )
        )
    return evidence_rows


def data_gap_summary(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for station in stations:
        evidence = station.get("dataEvidence")
        if not isinstance(evidence, list):
            continue
        missing = [
            {
                "key": item.get("key"),
                "status": item.get("status"),
                "message": item.get("message"),
            }
            for item in evidence
            if isinstance(item, dict) and int(item.get("count") or 0) == 0
        ]
        if missing:
            gaps.append({"station": station.get("key"), "label": station.get("label"), "missing": missing})
    return gaps


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
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    for station_key, override in overrides.items():
        station = ensure_station(stations, station_key, station_aliases=station_aliases)

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
    station_aliases = load_station_aliases()

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
        rankings, stations, station_urls = load_base_site_snapshot(station_aliases)
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
        rows = []
        for raw_row in read_csv(input_path):
            row = ranking_row(raw_row)
            row["station"] = canonical_station_key(row.get("station"), station_aliases)
            rows.append(row)
        rankings[window_key], _ = merge_ranking_rows_by_station(rows)

    if resolved_inputs.get("login_verification_checklist.csv"):
        checklist_rows = read_csv(resolved_inputs["login_verification_checklist.csv"])
        for row in checklist_rows:
            urls = [sanitize_public_text(url) for url in split_list(row.get("urls"))]
            station_key = canonical_station_key(row.get("station", ""), station_aliases)
            if not is_public_station_key(station_key):
                continue
            urls = [url for url in urls if is_public_station_url(url)]
            if not urls:
                continue
            ensure_station(
                stations,
                station_key,
                station_aliases=station_aliases,
                label=row.get("label", ""),
                url=urls[0] if urls else "",
                station_type=row.get("station_type", ""),
                platform_guess=row.get("platform_guess", ""),
            )
            for url in urls:
                add_station_url(station_urls, station_key, url, station_aliases)
            probe_final_url = sanitize_public_text(row.get("probe_final_url"))
            if probe_final_url:
                add_station_url(station_urls, station_key, probe_final_url, station_aliases)

    sync_station_rankings_from_rankings(stations, rankings, station_aliases=station_aliases)
    for window_rows in rankings.values():
        for row in window_rows:
            if row.get("stationUrl"):
                add_station_url(station_urls, row["station"], row["stationUrl"], station_aliases)

    if resolved_inputs.get("quality_metrics.csv"):
        for station in stations.values():
            station["quality"] = {}
        quality_rows = read_csv(resolved_inputs["quality_metrics.csv"])
        for raw_row in quality_rows:
            row = quality_row(raw_row)
            station_key = canonical_station_key(row["station"], station_aliases)
            if not is_public_station_key(station_key):
                continue
            row["station"] = station_key
            configured_urls = [sanitize_public_text(url) for url in split_list(raw_row.get("configured_urls"))]
            public_configured_urls = [url for url in configured_urls if is_public_station_url(url)]
            if station_key not in stations and not public_configured_urls:
                continue
            station = ensure_station(
                stations,
                station_key,
                station_aliases=station_aliases,
                label=row["label"],
                platform_guess=row["platformGuess"],
            )
            existing_quality = station["quality"].get(row["timeWindow"])
            station["quality"][row["timeWindow"]] = merge_quality_rows(existing_quality, row) if isinstance(existing_quality, dict) else row
            if public_configured_urls:
                for url in public_configured_urls:
                    add_station_url(station_urls, station_key, url, station_aliases)

    if resolved_inputs.get("multiplier_tiers.csv"):
        reset_station_tiers(stations)
        tier_rows = read_csv(resolved_inputs["multiplier_tiers.csv"])
        for row in tier_rows:
            station_key = canonical_station_key(row.get("station", ""), station_aliases)
            if not is_public_station_key(station_key):
                continue

            station = ensure_station(
                stations,
                station_key,
                station_aliases=station_aliases,
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
                add_station_url(station_urls, station_key, evidence_url, station_aliases)

    status_payloads = load_status_payloads(station_aliases)
    announcements = load_announcements(status_payloads)
    for station_key, payload in status_payloads.items():
        if not is_public_station_key(station_key):
            continue
        data = payload.get("data") if isinstance(payload, dict) else {}
        if isinstance(data, dict):
            source_url = sanitize_public_text(data.get("server_address"))
            if source_url:
                add_station_url(station_urls, station_key, source_url, station_aliases)

    pricing_snapshots = load_public_pricing_snapshots(station_aliases)
    apply_public_pricing_snapshots(stations, station_urls, pricing_snapshots, station_aliases=station_aliases)

    public_probes = load_public_probe_snapshots(station_aliases)
    for station_key, snapshot in public_probes.items():
        for url in snapshot.get("urls", []):
            add_station_url(station_urls, station_key, url, station_aliases)
        if station_key in stations:
            stations[station_key]["_publicProbeCaptured"] = True
            if snapshot.get("evidenceStatus", {}).get("publicProbe"):
                stations[station_key].setdefault("_publicEvidenceStatus", {})
                stations[station_key]["_publicEvidenceStatus"]["publicProbe"] = snapshot["evidenceStatus"]["publicProbe"]

    for station_key, rows in announcements.items():
        if not is_public_station_key(station_key):
            continue
        station = ensure_station(stations, station_key, station_aliases=station_aliases)
        station["announcements"] = merge_announcements(station.get("announcements", []), rows)

    live_snapshots = load_live_probe_snapshots(station_aliases)
    apply_live_probe_snapshots(stations, station_urls, live_snapshots, station_aliases=station_aliases)

    overrides = load_station_pricing_overrides(station_aliases)
    apply_station_pricing_overrides(stations, overrides, station_aliases=station_aliases)

    audit_targets = load_station_audit_targets(station_aliases)
    latest_audits = load_latest_station_audits(station_aliases)
    apply_audit_only_station_records(stations, station_urls, latest_audits, station_aliases=station_aliases)

    apply_authoritative_ranking_overrides(stations, rankings, overrides)

    station_list = sorted(
        [
            station
            for station in stations.values()
            if is_public_station_key(station.get("key")) and is_public_station_url(station.get("url"))
        ],
        key=lambda item: (
            item.get("rankings", {}).get("work_hours", {}).get("rank", 10**9),
            item.get("label", "").lower(),
        ),
    )

    for station in station_list:
        station["rechargeTiers"] = sort_recharge_tiers(station.get("rechargeTiers", []))
        url_choices = dedupe_strings(list(station_urls.get(station["key"], set())) + [station.get("url", "")])
        station["url"] = choose_best_url(url_choices)
        station["dataEvidence"] = build_station_evidence_status(station, live_snapshots.get(station["key"]))
        if station.get("_publicEvidenceStatus"):
            for item in station["dataEvidence"]:
                if item["key"] == "publicProbe":
                    item.update(station["_publicEvidenceStatus"]["publicProbe"])
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
        station.pop("_publicProbeCaptured", None)
        station.pop("_publicEvidenceStatus", None)

    sync_station_metadata_into_rows(stations, rankings)

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
                "data_gaps": data_gap_summary(station_list),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
