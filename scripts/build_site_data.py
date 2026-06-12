#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse, urlunparse

try:
    from scripts.station_display_names import contains_han, normalize_station_label
    from scripts.runtime_paths import (
        APP_ROOT,
        AUDIT_RUNS_DIR,
        DATA_DIR,
        LIVE_AUTH_PROBE_DIR,
        PENDING_API_PROBE_PATH,
        PUBLIC_FETCH_DIR,
        PUBLIC_FETCH_DIRS,
        SITE_DATA_PATH,
        WORKSPACE_ROOT,
        ensure_runtime_dirs,
        logical_data_path,
    )
except ModuleNotFoundError:
    from station_display_names import contains_han, normalize_station_label
    from runtime_paths import (
        APP_ROOT,
        AUDIT_RUNS_DIR,
        DATA_DIR,
        LIVE_AUTH_PROBE_DIR,
        PENDING_API_PROBE_PATH,
        PUBLIC_FETCH_DIR,
        PUBLIC_FETCH_DIRS,
        SITE_DATA_PATH,
        WORKSPACE_ROOT,
        ensure_runtime_dirs,
        logical_data_path,
    )


SOURCE_ROOTS = [APP_ROOT]
STATION_PRICING_OVERRIDES_PATH = APP_ROOT / "config" / "station_pricing_overrides.json"
STATION_URL_OVERRIDES_PATH = APP_ROOT / "config" / "station_url_overrides.json"
STATION_INVITE_LINKS_PATH = APP_ROOT / "config" / "station_invite_links.json"
INVITE_LINK_REPORT_PATH = APP_ROOT / ".local-artifacts" / "station-invite-link-report.json"
STATION_AUDIT_TARGETS_PATH = APP_ROOT / "config" / "station_audit_targets.json"
STATION_ALIASES_PATH = APP_ROOT / "config" / "station_aliases.json"
GENERATED_AT_ENV = "SITE_DATA_GENERATED_AT"
POSTGRES_BASE_MERGE_ENV = "SITE_DATA_MERGE_POSTGRES_BASE"

SHORT_TYPE_LABELS = {
    "subscription": "包月型",
    "non_subscription": "非包月型",
    "mixed": "混合型",
    "charity": "公益站",
    "unknown_pending": "待补证据",
}

FULL_TYPE_LABELS = {
    "subscription": "包月型中转站",
    "non_subscription": "非包月型中转站",
    "mixed": "混合型中转站",
    "charity": "公益站",
    "unknown_pending": "待补证据",
}

BILLING_LABELS = {
    "monthly": "月卡",
    "weekly": "周卡",
    "daily": "日卡",
    "quarterly": "季卡",
    "permanent": "永久额度",
    "free": "免费额度",
    "permanent_or_unknown": "按量额度",
}
PACKAGE_BILLING_TYPES = {"monthly", "weekly", "daily", "quarterly", "yearly"}
PRIORITY_RANKING_MIN_REQUESTS = 10

TIME_WINDOWS = {
    "work_hours": {"key": "work_hours", "label": "工作时段", "range": "工作日09:00:00-18:00:00"},
    "off_hours": {"key": "off_hours", "label": "非工作时段", "range": "工作日18:00:01-次日08:59:59；周末全天"},
    "all_hours": {"key": "all_hours", "label": "全时段", "range": "00:00:00-23:59:59"},
}

HIGHLIGHT_PHRASE = "所以本排名更关注各中转站的服务下限。"
DISCLAIMER_EMPHASIS = "部分中转站外链使用邀请链接，可能为测试账号带来少量额度奖励。这些额度将用于维持长期测试、扩大数据样本并持续更新排名；排名数据、评分和排序不受邀请链接影响，仅供参考。"
EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b")
PATH_PATTERN = re.compile(r"([A-Za-z]:\\Users\\)([^\\`]+)")
LOCALHOST_PATTERN = re.compile(r"^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$", re.IGNORECASE)
PUBLIC_TTOP5_URLS = {"https://ttop5.gettoken.dev"}
TOPUP_NAME_PATTERN = re.compile(r"wallet topup (\d+(?:\.\d+)?) RMB", re.IGNORECASE)
TOPUP_HTML_PATTERN = re.compile(
    r"(wallet\s*topup\s*(\d+(?:\.\d+)?)\s*RMB).*?(\d+(?:\.\d+)?)\s*(?:USD|\$)",
    re.IGNORECASE | re.DOTALL,
)
WALLET_CONVERSION_PATTERNS = (
    re.compile(r"[\u00a5\uffe5]\s*(\d+(?:\.\d+)?)\s*=\s*\$\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:RMB|CNY|\u4eba\u6c11\u5e01)\s*=\s*\$\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
)
MINIMUM_RECHARGE_PATTERN = re.compile(
    r"(?:\u6700\u4f4e|\u8d77\u5145|minimum)\s*(?:[\u00a5\uffe5]|RMB|CNY|\u4eba\u6c11\u5e01)?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
PUBLIC_PLAN_CARD_PATTERN = re.compile(
    r"<article\b[^>]*class=[\"'][^\"']*\bffm-plan-card\b[^\"']*[\"'][^>]*>(.*?)</article>",
    re.IGNORECASE | re.DOTALL,
)
APP_CONFIG_PATTERN = re.compile(
    r"window\.__APP_CONFIG__\s*=\s*(\{.*?\})\s*;?\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
FENCED_CODE_BLOCK_PATTERN = re.compile(r"(^```[^\n]*\n[\s\S]*?^```[ \t]*$)", re.MULTILINE)
PAY_SHOP_PATTERN = re.compile(r"https?://pay\.ldxp\.cn/shop/([A-Za-z0-9_-]+)")
TRAILING_UI_SEGMENTS = {"console", "dashboard", "wallet", "keys", "purchase", "pricing", "plans", "api-keys"}
LOCALE_SEGMENT_PATTERN = re.compile(r"^[A-Za-z]{2}(?:-[A-Za-z]{2})?$")
PAYMENT_URL_PATH_SEGMENTS = {"shop", "item", "pay", "checkout", "payment"}
KRILL_ROUTE_MULTIPLIER = 0.2


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


def postgres_base_merge_enabled() -> bool:
    return parse_bool(os.environ.get(POSTGRES_BASE_MERGE_ENV))


def parse_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y"}:
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
    if text in PUBLIC_TTOP5_URLS:
        return text
    text = re.sub(r"(?i)ttop5", "xxx", text)
    return text


def public_source_text(value: Any) -> str:
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""
    if re.match(r"^[A-Za-z]:\\", raw):
        path = Path(raw)
        for root in (APP_ROOT, WORKSPACE_ROOT):
            try:
                return path.resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                continue
        return path.name
    text = sanitize_public_text(raw)
    if re.match(r"^[A-Za-z]:\\", text):
        return Path(text).name
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
    if "://" in text:
        return False
    if any(ch in text for ch in "（）()"):
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


def station_display_label(station_key: Any, raw_label: Any = "", station_url: Any = "") -> str:
    return normalize_station_label(
        sanitize_public_text(station_key),
        sanitize_public_text(raw_label),
        sanitize_public_text(station_url),
    )


class AnnouncementHtmlTextParser(HTMLParser):
    BLOCK_TAGS = {"address", "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ol", "p", "section", "table", "tr", "ul"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.href_stack: list[str] = []

    def append_break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "br" or (lowered in self.BLOCK_TAGS and lowered not in {"p", "li"}):
            self.append_break()
        if lowered == "li":
            self.append_break()
            self.parts.append("- ")
        if lowered == "a":
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value
                    break
            self.href_stack.append(href)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "a":
            href = self.href_stack.pop() if self.href_stack else ""
            if href.startswith(("http://", "https://")):
                current_line = "".join(self.parts).split("\n")[-1]
                if href not in current_line:
                    self.parts.append(f" {href}")
        if lowered in self.BLOCK_TAGS:
            self.append_break()

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def text(self) -> str:
        text = "".join(self.parts)
        text = unescape(text)
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r" *\n+ *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(value: Any) -> str:
    text = str(value or "")
    if not re.search(r"<[A-Za-z][^>]*>", text):
        return unescape(text)
    parser = AnnouncementHtmlTextParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", "", unescape(text))
    return parser.text()


def normalize_announcement_text(value: Any) -> str:
    text = sanitize_public_text(html_to_text(value))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return normalize_announcement_markdown(text.strip())


def transform_markdown_outside_code_fences(text: str, transform: Callable[[str], str]) -> str:
    parts = FENCED_CODE_BLOCK_PATTERN.split(text)
    if len(parts) == 1:
        return transform(text)
    normalized_parts: list[str] = []
    for index, part in enumerate(parts):
        normalized_parts.append(part if index % 2 else transform(part))
    return "".join(normalized_parts)


def normalize_announcement_markdown(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""

    def replace_legacy_image(match: re.Match[str]) -> str:
        image_url = match.group("image").strip()
        href = (match.group("href") or "").strip()
        group_names = match.re.groupindex
        alt = (match.group("alt") if "alt" in group_names else "image") or "image"
        alt = str(alt).strip()
        token = f"![{alt}]({image_url})"
        return f"[{token}]({href})" if href else token

    def normalize_segment(segment: str) -> str:
        normalized = re.sub(
            r"!\[\[(?P<alt>[^\]]+)\]\((?P<image>https?://[^)\s]+)\]\((?P<href>https?://[^)\s]+)\)\)",
            replace_legacy_image,
            segment,
        )
        normalized = re.sub(
            r"(?im)^!image\s+(?P<image>https?://\S+)(?:\s+(?P<href>https?://\S+))?\s*$",
            replace_legacy_image,
            normalized,
        )
        normalized = re.sub(
            r"(?im)^!(?!\[)(?P<alt>[^\s].*?)\s+(?P<image>https?://\S+)\s+(?P<href>https?://\S+)\s*$",
            replace_legacy_image,
            normalized,
        )
        normalized = re.sub(
            r"(?im)^(?P<label>[^\n\[]*?\S)\s+(?P<url>https?://[^\s)]+)\s*$",
            lambda match: f"[{match.group('label').strip()}]({match.group('url').strip()})",
            normalized,
        )
        normalized = re.sub(r"(?im)^(\s*[-*]\s+Telegram:\s+)(https?://\S+)(?:\s+\2)+\s*$", r"\1[\2](\2)", normalized)
        normalized = re.sub(r"(?im)^(\s*>\s*.+?:\s+)(https?://\S+)(?:\s+\2)+\s*$", r"\1[\2](\2)", normalized)
        normalized = re.sub(r"(?im)^(\s*.+?:\s+)(https?://\S+)(?:\s+\2)+\s*$", r"\1[\2](\2)", normalized)
        normalized = re.sub(r"[ \t]+\n", "\n", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized

    return transform_markdown_outside_code_fences(text, normalize_segment).strip()


def announcement_dedupe_fingerprint(value: Any) -> str:
    text = normalize_announcement_markdown(value)
    if not text:
        return ""

    def image_link_to_semantic(match: re.Match[str]) -> str:
        alt = re.sub(r"\s+", " ", match.group("alt").strip())
        image_url = match.group("image").strip()
        href = match.group("href").strip()
        return f"{alt} {image_url} {href}".strip()

    def image_to_semantic(match: re.Match[str]) -> str:
        alt = re.sub(r"\s+", " ", match.group("alt").strip())
        image_url = match.group("image").strip()
        return f"{alt} {image_url}".strip()

    def link_to_semantic(match: re.Match[str]) -> str:
        label = re.sub(r"\s+", " ", match.group("label").strip())
        href = match.group("href").strip()
        return f"{label} {href}".strip()

    def fingerprint_segment(segment: str) -> str:
        fingerprint = re.sub(
            r"\[!\[(?P<alt>[^\]]*)\]\((?P<image>https?://[^)\s]+)\)\]\((?P<href>https?://[^)\s]+)\)",
            image_link_to_semantic,
            segment,
        )
        fingerprint = re.sub(
            r"!\[(?P<alt>[^\]]*)\]\((?P<image>https?://[^)\s]+)\)",
            image_to_semantic,
            fingerprint,
        )
        fingerprint = re.sub(
            r"\[(?P<label>[^\]]+)\]\((?P<href>https?://[^)\s]+)\)",
            link_to_semantic,
            fingerprint,
        )
        fingerprint = re.sub(r"(?im)^\s*[-*_]{3,}\s*$", " ", fingerprint)
        fingerprint = re.sub(r"(?im)^\s{0,3}(#{1,6}\s+|>\s+|[-*+]\s+|\d+\.\s+)", "", fingerprint)
        fingerprint = re.sub(r"[ \t]+", " ", fingerprint)
        fingerprint = re.sub(r"\s*\n\s*", " ", fingerprint)
        fingerprint = re.sub(r"\s{2,}", " ", fingerprint)
        return fingerprint.strip()

    parts: list[str] = []
    for index, part in enumerate(FENCED_CODE_BLOCK_PATTERN.split(text)):
        if not part:
            continue
        if index % 2:
            parts.append(part.strip())
            continue
        fingerprint = fingerprint_segment(part)
        if fingerprint:
            parts.append(fingerprint)
    return "\n".join(parts).strip()


def announcement_quality_score(item: dict[str, Any], normalized_content: str) -> tuple[int, int, int]:
    content = str(item.get("content") or "")
    content_html = str(item.get("contentHtml") or "")
    has_markdown_image = int("[![" in normalized_content or "![" in normalized_content)
    has_markdown_link = int(bool(re.search(r"\[[^\]]+\]\((https?://[^)\s]+)\)", normalized_content)))
    has_html = int(bool(content_html))
    has_html_image = int(bool(re.search(r"<img\b", content_html, flags=re.IGNORECASE)))
    return (
        has_html * 20 + has_html_image * 10 + has_markdown_image * 10 + has_markdown_link * 5,
        len(normalized_content),
        len(content) + len(content_html),
    )


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


def public_url_host(value: Any) -> str:
    parsed = urlparse(sanitize_public_text(value))
    if parsed.scheme not in {"http", "https"}:
        return ""
    return (parsed.hostname or "").lower().removeprefix("www.")


def find_station_key_by_url_host(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    url: Any,
) -> str:
    target_host = public_url_host(url)
    if not target_host:
        return ""

    for station_key, station in stations.items():
        candidate_urls = dedupe_strings([station.get("url", ""), *station_urls.get(station_key, set())])
        if any(public_url_host(candidate_url) == target_host for candidate_url in candidate_urls):
            return station_key
    return ""


def is_payment_evidence_url(value: Any) -> bool:
    text = sanitize_public_text(value)
    if not text:
        return False
    parsed = urlparse(text)
    host = parsed.netloc.lower()
    if host.startswith("pay.") or ".pay." in host:
        return True
    segments = [segment.lower() for segment in parsed.path.split("/") if segment]
    return any(segment in PAYMENT_URL_PATH_SEGMENTS for segment in segments)


def choose_display_url(
    station_key: str,
    urls: list[str],
    url_overrides: dict[str, str] | None = None,
    current_url: Any = "",
) -> str:
    override_url = sanitize_public_text((url_overrides or {}).get(station_key))
    if override_url and is_public_station_url(override_url):
        return override_url

    current_candidates = [
        url
        for url in extract_public_url_candidates(current_url)
        if not is_payment_evidence_url(url)
    ]
    if current_candidates:
        return choose_best_url(current_candidates)

    expanded_urls = dedupe_strings(
        candidate
        for url in urls
        for candidate in extract_public_url_candidates(url)
    )
    preferred_urls = [url for url in expanded_urls if not is_payment_evidence_url(url)]
    return choose_best_url(preferred_urls or urls)


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
    generated_at = str(os.environ.get(GENERATED_AT_ENV, "")).strip()

    if not generated_at and summary_path and summary_path.exists():
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
                "建议优先使用官方渠道。官方账号目前获取方式相对简单，网上也有很多教程，这里不再展开。中转站更适合作为备用选项，不建议作为长期主力方案。",
                "中转站服务质量参差不齐，普遍存在错误响应率更高、响应时间更长、稳定性更差等问题。同时，计费规则不够透明，价格倍率也可能频繁变动。",
                "中转站还存在模型质量不稳定、计费不清晰、数据安全风险较高，以及随时关停或跑路的风险。如果确实需要使用，建议少量多次充值，控制损失风险。",
            ],
            "items": [
                "工作时段：周一至周五 09:00:00-18:00:00。",
                "非工作时段：工作日 18:00:01-次日 08:59:59；周末全天计入非工作时段。",
                "正式综合排名仅使用高置信度或人工核验的费用证据；0 倍率分组不参与排名。",
                "正式采用倍率优先使用 Codex 口径分组中的最小非 0 倍率；有明确用途标记时先排除非 Codex 分组。",
                "sub2api 站点的公告、分组倍率、订阅和充值计划通常需要登录后查看；公开抓取只作为首页配置、文档链接和菜单项补充。",
                DISCLAIMER_EMPHASIS,
            ],
            "environment": "\n\n".join(
                [
                    "本次数据来自本人电脑上 Codex Manager 对多家中转站 Codex API Key 的聚合调用日志，使用场景为 Codex 接入开发。",
                    "由于所有请求均先经过 Codex Manager，再转发至各中转站，相比直连会天然增加一层延迟。",
                    "日志样本来自本人实际开发个人小项目期间的调用记录，网络环境为昆明广电宽带。以下排名仅反映本人使用时间点、当时账号状态与当时网络环境下的观测结果。",
                    "测试账号多由本人手动注册，额度来自新用户赠额、活动赠额、少量小额充值，及少数收录站点送测；仅用于可用性观察、扩大样本和持续更新，不影响评分、排序和费用口径。",
                    f"费用口径统一按各站当前可核验的 Codex 口径最小非 0 分组倍率计算；有明确用途标记时先排除非 Codex 分组，未显式区分时再回退到最低非 Claude 分组。该档位通常价格最低，但也往往延迟更高、稳定性更差，{HIGHLIGHT_PHRASE}",
                ]
            ),
            "coreItems": [
                "综合评分权重 = 正确响应率 40% + 响应时间 35% + 实际倍率 25%。",
                "实际倍率 = 分组倍率 × 实付金额 ÷ 到账美元额度。",
                "正式采用倍率 = Codex 口径分组倍率（最小非 0 倍率） × 实付金额 ÷ 到账美元额度。",
                "Codex 口径分组：优先尊重人工或结构化用途标记；没有标记时按分组名排除 Claude/国产/公益等非 Codex 分组。",
                "正确响应定义：HTTP 2xx 且 error IS NULL；HTTP 200 但 error 非空也计为错误响应；因欠费、充值解锁、手机号验证等账户前置条件导致的错误样本，已从正确响应率统计中剔除。部分请求报错（如502）但能正常使用时，也计为错误响应。",
            ],
            "formula": "实际倍率 = 分组倍率 × 实付金额 ÷ 到账美元额度。",
            "adoptedMultiplierRule": "正式采用倍率：优先取 Codex 口径分组中的最小非 0 实际倍率；有明确用途标记时排除非 Codex 分组，否则按名称规则排除 Claude/国产/公益等分组。",
            "scoring": "综合评分权重 = 正确响应率 40% + 响应时间 35% + 实际倍率 25%。",
        },
    }


def ranking_row(row: dict[str, str]) -> dict[str, Any]:
    adopted_tier = sanitize_public_text(row.get("adopted_tier"))
    adopted_group, adopted_recharge = (adopted_tier.split(" | ", 1) + [""])[:2] if adopted_tier else ("", "")
    station_type = row.get("station_type", "unknown_pending")
    station_key = row.get("station", "")
    station_url = sanitize_public_text(row.get("station_url"))
    return {
        "rank": parse_int(row.get("rank")),
        "rankingBasis": sanitize_public_text(row.get("ranking_basis")),
        "timeWindow": row.get("time_window", ""),
        "timeWindowLabel": sanitize_public_text(row.get("time_window_label")),
        "station": station_key,
        "label": station_display_label(station_key, row.get("label"), station_url),
        "stationUrl": station_url,
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
    station_key = row.get("station", "")
    return {
        "station": station_key,
        "label": station_display_label(station_key, row.get("label")),
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


def normalize_audit_detector_result(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    key = sanitize_public_text(item.get("key"))
    label = sanitize_public_text(item.get("label"))
    category = sanitize_public_text(item.get("category"))
    status = sanitize_public_text(item.get("status"))
    summary = normalize_public_text(item.get("summary"))
    if not key or not label or not category or not status:
        return None
    score = parse_int(item.get("score")) if item.get("score") is not None else None
    weight = parse_int(item.get("weight")) if item.get("weight") is not None else None
    payload: dict[str, Any] = {
        "key": key,
        "label": label,
        "category": category,
        "status": status,
        "severity": sanitize_public_text(item.get("severity")),
        "summary": summary,
    }
    if score is not None:
        payload["score"] = score
    if weight is not None:
        payload["weight"] = weight
    evidence = [normalize_public_text(value) for value in item.get("evidence", []) if normalize_public_text(value)]
    if evidence:
        payload["evidence"] = evidence
    return payload


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
    audit_score = parse_int(item.get("auditScore")) if item.get("auditScore") is not None else None
    if audit_score is not None:
        payload["auditScore"] = max(0, min(100, audit_score))
    for source_key, target_key in [
        ("auditVerdictReason", "auditVerdictReason"),
        ("capabilityVerdict", "capabilityVerdict"),
        ("protocolVerdict", "protocolVerdict"),
        ("authenticityVerdict", "authenticityVerdict"),
        ("longContextVerdict", "longContextVerdict"),
        ("runMode", "runMode"),
        ("costNotice", "costNotice"),
    ]:
        value = normalize_public_text(item.get(source_key))
        if value:
            payload[target_key] = value
    detector_results = []
    for raw_detector in item.get("detectorResults", []):
        detector = normalize_audit_detector_result(raw_detector)
        if detector:
            detector_results.append(detector)
    if detector_results:
        payload["detectorResults"] = detector_results
    critical_findings = [normalize_public_text(value) for value in item.get("criticalFindings", []) if normalize_public_text(value)]
    if critical_findings:
        payload["criticalFindings"] = critical_findings
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
    display_url = sanitize_public_text(overrides.get("url")) if raw_station_key == station_key else ""
    display_label = station_display_label(station_key, overrides.get("label"), display_url)
    record = container.setdefault(
        station_key,
        {
            "key": station_key,
            "label": display_label,
            "url": display_url,
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
        record["label"] = station_display_label(station_key, overrides["label"], record.get("url"))
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
            content = normalize_announcement_text(item.get("content"))
            if not content:
                continue
            content_html = str(item.get("contentHtml") or "").strip()
            rows.append(
                {
                    "id": str(item.get("id") or index),
                    "publishedAt": str(
                        item.get("publishDate")
                        or item.get("publishedAt")
                        or item.get("published_at")
                        or item.get("createdAt")
                        or item.get("created_at")
                        or item.get("updatedAt")
                        or item.get("updated_at")
                        or ""
                    ),
                    "type": normalize_announcement_text(item.get("type") or "default"),
                    "extra": normalize_announcement_text(item.get("extra")),
                    "content": content,
                    **({"contentHtml": content_html} if content_html else {}),
                    "sourceUrl": source_url,
                }
            )
        grouped[station_key] = rows
    return grouped


def load_live_auth_probes(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    if LIVE_AUTH_PROBE_DIR.exists():
        for path in sorted(LIVE_AUTH_PROBE_DIR.glob("*-live-auth-probe.json")):
            station_key = canonical_station_key(path.name.removesuffix("-live-auth-probe.json"), station_aliases)
            if not is_public_station_key(station_key):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                payload["_probePath"] = logical_data_path(path) if path.is_relative_to(DATA_DIR) else str(path)
                grouped[station_key] = payload
    for station_key, pending in load_pending_api_probes(station_aliases).items():
        current = grouped.get(station_key)
        if current is None or not probe_has_useful_detail_data(current):
            grouped[station_key] = pending
    return grouped


def load_pending_api_probes(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    if not PENDING_API_PROBE_PATH.exists():
        return {}
    try:
        payload = json.loads(PENDING_API_PROBE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    grouped: dict[str, dict[str, Any]] = {}
    for station, record in payload.items():
        station_key = canonical_station_key(str(station), station_aliases)
        if not is_public_station_key(station_key) or not isinstance(record, dict):
            continue
        normalized = normalize_pending_api_probe(record)
        if probe_has_useful_detail_data(normalized):
            grouped[station_key] = normalized
    return grouped


def normalize_pending_api_probe(record: dict[str, Any]) -> dict[str, Any]:
    state = record.get("state") if isinstance(record.get("state"), dict) else {}
    results = record.get("results") if isinstance(record.get("results"), dict) else {}
    normalized_results: dict[str, Any] = results
    if record.get("probe_kind") == "new_api" and "/api/user/self/groups" in results:
        normalized_results = {"New-Api-User:pending": results}
    return {
        "location": state.get("location") or record.get("url") or "",
        "url": record.get("url") or state.get("location") or "",
        "title": state.get("title") or record.get("title") or "",
        "results": normalized_results,
        "_probePath": logical_data_path(PENDING_API_PROBE_PATH) if PENDING_API_PROBE_PATH.is_relative_to(DATA_DIR) else str(PENDING_API_PROBE_PATH),
    }


def body_has_nonempty_data(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    data = body.get("data")
    if isinstance(data, (list, dict)):
        return bool(data)
    return data not in (None, "", [])


def probe_has_useful_detail_data(probe: dict[str, Any]) -> bool:
    results = probe.get("results")
    if not isinstance(results, dict):
        return False
    buckets = [results]
    buckets.extend(bucket for bucket in results.values() if isinstance(bucket, dict))
    detail_paths = (
        "/api/user/self/groups",
        "/api/user/topup/info",
        "/api/subscription/plans",
        "/api/endpoint-settings/me",
        "/api/plans",
        "/api/public/shop/products",
        "/api/announcements/unread",
        "/api/auth/me",
        "/api/billing",
        "/api/usage",
        "/api/v1/groups/available",
        "/api/v1/payment/plans",
        "/api/v1/payment/checkout-info",
    )
    for bucket in buckets:
        for path in detail_paths:
            entry = bucket.get(path)
            body = entry.get("body") if isinstance(entry, dict) else None
            if body_has_nonempty_data(body):
                return True
        amount_results = bucket.get("/api/user/amount")
        if isinstance(amount_results, dict) and amount_results:
            return True
    return False


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
    if any(
        lowered.startswith(marker)
        for marker in (
            "404 page not found",
            "404 not found",
            "not found",
            "authorization header is required",
            "unauthorized",
            "invalid token",
            "forbidden",
        )
    ):
        return False
    if re.match(r"^\d{3}\s", lowered):
        return False
    return True


def extract_collection(raw: Any, *, allow_text_item: bool = False) -> tuple[list[Any], bool]:
    if isinstance(raw, list):
        return raw, True
    if allow_text_item and isinstance(raw, str) and looks_like_notice_text(raw):
        return [{"content": raw}], True
    if not isinstance(raw, dict):
        return [], False
    for key in ("announcement", "notice"):
        if key not in raw:
            continue
        item = raw.get(key)
        if item is None:
            return [], True
        if isinstance(item, list):
            return item, True
        if isinstance(item, dict):
            return [item], True
        if allow_text_item and isinstance(item, str) and looks_like_notice_text(item):
            return [{"content": item}], True
    for key in ("announcements", "items", "list", "records", "rows", "data"):
        if key not in raw:
            continue
        rows, found = extract_collection(raw.get(key), allow_text_item=allow_text_item)
        if found:
            return rows, True
    return [], False


def normalize_live_announcement(station_key: str, item: dict[str, Any], index: int, source_url: str) -> dict[str, Any] | None:
    title = normalize_announcement_text(item.get("title") or item.get("name") or item.get("subject"))
    content = normalize_announcement_text(
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
    extra = normalize_announcement_text(item.get("extra") or item.get("summary") or "")
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
    override = probe.get("announcementStatus")
    if isinstance(override, dict):
        status = sanitize_public_text(override.get("status"))
        if status in {"captured", "empty", "failed", "missing", "login_required", "blocked", "public_missing"}:
            return [], {
                "status": status,
                "source": public_source_text(override.get("source") or probe_location(probe)),
                "message": normalize_public_text(override.get("message"))
                or "live auth probe reported an explicit announcement status.",
            }

    first_failure: dict[str, str] | None = None
    first_empty: dict[str, str] | None = None
    for api_path in (
        "/api/v1/announcements",
        "/api/announcements",
        "/api/announcements/unread",
        "/api/announcements/active?locale=zh-CN",
        "/api/announcements/active?locale=en",
        "/api/user/announcements",
        "/api/user/announcements/unread-popup",
        "/api/user/announcements/unread-count",
        "/api/status",
        "/api/notice",
        "/api/notices",
    ):
        entry = find_probe_result(probe, api_path)
        if entry is None:
            continue
        status = int(entry.get("status") or 0)
        ok = bool(entry.get("ok"))
        body = probe_result_body_from_entry(entry)
        rows, found = extract_collection(
            body,
            allow_text_item="notice" in api_path.lower(),
        )
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
        "source": public_source_text(probe.get("_probePath") or probe_location(probe)),
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
    new_api_result = new_api_group_rows(probe)
    if new_api_result is not None:
        return new_api_result
    krill_result = krill_route_group_rows(probe)
    if krill_result is not None:
        return krill_result
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
    return [], {"status": "missing", "source": public_source_text(probe.get("_probePath") or probe_location(probe)), "message": "live auth probe 尚未包含分组接口"}


def duration_unit_to_billing_type(unit: Any) -> str:
    text = str(unit or "").strip().lower()
    if text in {"month", "monthly"}:
        return "monthly"
    if text in {"week", "weekly"}:
        return "weekly"
    if text in {"day", "daily"}:
        return "daily"
    if text in {"quarter", "quarterly"}:
        return "quarterly"
    if text in {"year", "yearly"}:
        return "monthly"
    return "permanent"


def billing_type_from_days(days: Any) -> str:
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


def plan_expires_rule(plan: dict[str, Any]) -> str:
    subtitle = sanitize_public_text(plan.get("subtitle") or plan.get("description") or plan.get("desc"))
    validity_days = parse_float(plan.get("validity_days"))
    if validity_days:
        base = f"{format_plain_number(validity_days)} day package"
    elif parse_float(plan.get("duration_value")) and str(plan.get("duration_unit") or "").strip():
        unit = str(plan.get("duration_unit") or "").strip()
        base = f"{format_plain_number(parse_float(plan.get('duration_value')))} {unit} subscription"
    else:
        base = subtitle or "Subscription package"
    quota_reset_period = str(plan.get("quota_reset_period") or "").strip().lower()
    if quota_reset_period == "never":
        base = f"{base}; total quota pool, no periodic reset"
    elif quota_reset_period in {"daily", "weekly", "monthly"}:
        base = f"{base}; quota resets {quota_reset_period}"
    return base


def convert_quota_to_usd(quota_value: Any) -> float | None:
    raw = parse_float(quota_value)
    if raw is None:
        return None
    return raw / 500000.0


def plan_total_usd(plan: dict[str, Any]) -> float | None:
    for key in ("usd_amount", "usdAmount", "usd", "amount_usd", "charge_price", "quota_amount", "credit_amount", "monthly_limit_usd", "weekly_limit_usd", "daily_limit_usd"):
        direct = parse_float(plan.get(key))
        if direct and direct > 0:
            if key == "daily_limit_usd":
                duration_days = parse_float(plan.get("validity_days") or plan.get("duration_value")) or 1
                return direct * max(1, duration_days)
            if key == "weekly_limit_usd":
                duration_days = parse_float(plan.get("validity_days") or plan.get("duration_value")) or 7
                return direct * max(1, int(duration_days // 7))
            return direct
    amount = parse_float(plan.get("amount"))
    price = parse_float(plan.get("price_amount") or plan.get("price") or plan.get("rmbAmount") or plan.get("rmb_amount"))
    if amount and amount > 0 and price is not None:
        return amount
    quota_usd = convert_quota_to_usd(plan.get("total_amount"))
    if quota_usd is None:
        quota_usd = convert_quota_to_usd(plan.get("quota"))
    if quota_usd:
        return quota_usd
    description = str(plan.get("description") or plan.get("subtitle") or plan.get("desc") or "")
    match = re.search(r"(?:\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:USD|usd|\$))", description)
    if match:
        return parse_float(match.group(1) or match.group(2))
    return None


def plan_billing_type(plan: dict[str, Any]) -> str:
    explicit = sanitize_public_text(plan.get("billing_type") or plan.get("billingType"))
    if explicit:
        return explicit
    validity_days = parse_float(plan.get("validity_days"))
    if validity_days:
        return billing_type_from_days(validity_days)
    return duration_unit_to_billing_type(plan.get("duration_unit") or plan.get("validity_unit"))


def new_api_auth_bucket(probe: dict[str, Any]) -> dict[str, Any] | None:
    results = probe.get("results")
    if not isinstance(results, dict):
        return None
    if isinstance(results.get("/api/user/self/groups"), dict):
        return results
    candidates: list[dict[str, Any]] = []
    for key, bucket in results.items():
        if isinstance(key, str) and key.startswith("New-Api-User:") and isinstance(bucket, dict):
            candidates.append(bucket)
    for bucket in candidates:
        for path in ("/api/user/self/groups", "/api/user/topup/info", "/api/subscription/plans"):
            entry = bucket.get(path)
            body = entry.get("body") if isinstance(entry, dict) else None
            if isinstance(body, dict) and (body.get("success") is True or body.get("code") == 0):
                return bucket
        amount_results = bucket.get("/api/user/amount")
        if isinstance(amount_results, dict):
            for entry in amount_results.values():
                body = entry.get("body") if isinstance(entry, dict) else None
                if isinstance(body, dict) and (body.get("success") is True or body.get("code") == 0):
                    return bucket
    if candidates:
        return candidates[0]
    return None


def new_api_group_rows(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]] | None:
    bucket = new_api_auth_bucket(probe)
    if bucket is None:
        return None
    entry = bucket.get("/api/user/self/groups")
    data = probe_result_data_from_entry(entry if isinstance(entry, dict) else None)
    groups: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for group_name, group_info in data.items():
            if not isinstance(group_info, dict):
                continue
            group = normalize_group_row(
                {
                    "groupName": group_name,
                    "groupMultiplier": group_info.get("ratio") or group_info.get("multiplier"),
                }
            )
            if group:
                groups.append(group)
    source = probe_source_url(probe, "/api/user/self/groups")
    if groups:
        return groups, {"status": "captured", "source": source, "message": f"登录态分组接口抓取到 {len(groups)} 条"}
    if isinstance(entry, dict):
        return [], {"status": "empty", "source": source, "message": "登录态 New API 分组接口返回空列表"}
    return [], {"status": "missing", "source": public_source_text(probe.get("_probePath") or probe_location(probe)), "message": "live auth probe 尚未包含 New API 分组接口"}


def krill_route_group_rows(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]] | None:
    entry = find_probe_result(probe, "/api/endpoint-settings/me")
    if entry is None:
        return None
    data = probe_result_data_from_entry(entry)
    routes = data.get("routes") if isinstance(data, dict) else None
    groups: list[dict[str, Any]] = []
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, dict) or explicitly_false(route.get("enabled")):
                continue
            route_name = sanitize_public_text(route.get("name") or route.get("key"))
            if not route_name:
                continue
            group = normalize_group_row(
                {
                    "groupName": route_name,
                    "groupMultiplier": KRILL_ROUTE_MULTIPLIER,
                }
            )
            if group:
                groups.append(group)
    source = probe_source_url(probe, "/api/endpoint-settings/me")
    if groups:
        return groups, {"status": "captured", "source": source, "message": f"Krill 路由配置抓取到 {len(groups)} 条；Codex 套餐页显示倍率全部 0.2x"}
    if entry_is_blocked(entry):
        return [], {"status": "blocked", "source": source, "message": "Krill 路由配置接口被验证码或风控阻断"}
    status = int(entry.get("status") or 0)
    message = f"Krill 路由配置接口返回 HTTP {status}" if status >= 400 else "Krill 路由配置接口返回空列表"
    return [], {"status": "empty" if status < 400 else "failed", "source": source, "message": message}


def new_api_recharge_rows(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]] | None:
    bucket = new_api_auth_bucket(probe)
    if bucket is None:
        return None
    topup_entry = bucket.get("/api/user/topup/info")
    topup_data = probe_result_data_from_entry(topup_entry if isinstance(topup_entry, dict) else None)
    topup_data = topup_data if isinstance(topup_data, dict) else {}
    amount_options = topup_data.get("amount_options") if isinstance(topup_data.get("amount_options"), list) else []
    discount_map = topup_data.get("discount") if isinstance(topup_data.get("discount"), dict) else {}
    amount_results = bucket.get("/api/user/amount")
    amount_results = amount_results if isinstance(amount_results, dict) else {}
    tiers: list[dict[str, Any]] = []
    for amount in amount_options:
        rmb_amount = parse_float(amount)
        if rmb_amount is None or rmb_amount <= 0:
            continue
        amount_key = str(int(rmb_amount)) if rmb_amount.is_integer() else str(rmb_amount)
        entry = amount_results.get(amount_key)
        data = probe_result_data_from_entry(entry if isinstance(entry, dict) else None)
        usd_amount = parse_float(data)
        if usd_amount is None:
            continue
        discount = parse_float(discount_map.get(amount_key)) or 1.0
        note = "Wallet API conversion sample from /api/user/amount; not a fixed package"
        if discount != 1.0:
            note = f"{note}; discount {format_plain_number(discount)}"
        row = normalize_recharge_row(
            {
                "rechargeName": f"wallet topup sample {format_plain_number(rmb_amount)} RMB",
                "billingType": "permanent",
                "rmbAmount": rmb_amount,
                "usdAmount": usd_amount,
                "rechargeLocation": "wallet API -> /api/user/amount sample",
                "expiresRule": note,
            }
        )
        if row:
            tiers.append(row)

    plan_entry = bucket.get("/api/subscription/plans")
    plan_rows, _found = extract_collection(probe_result_data_from_entry(plan_entry if isinstance(plan_entry, dict) else None))
    seen_plans: set[tuple[Any, ...]] = set()
    for item in plan_rows:
        if not isinstance(item, dict):
            continue
        plan = dict(item.get("plan") if isinstance(item.get("plan"), dict) else item)
        title = sanitize_public_text(plan.get("title") or plan.get("name") or plan.get("product_name") or "subscription plan")
        price = parse_float(
            plan.get("price_amount")
            or plan.get("price")
            or plan.get("amount")
            or plan.get("rmbAmount")
            or plan.get("rmb_amount")
        )
        usd_amount = plan_total_usd(plan)
        key = (plan.get("id"), title, price, usd_amount)
        if key in seen_plans:
            continue
        seen_plans.add(key)
        row = normalize_recharge_row(
            {
                "rechargeName": title,
                "billingType": plan_billing_type(plan),
                "rmbAmount": price,
                "usdAmount": usd_amount,
                "rechargeLocation": "subscription plans API",
                "expiresRule": plan_expires_rule(plan),
            }
        )
        if row:
            tiers.append(row)

    source = probe_source_url(probe, "/api/subscription/plans" if plan_rows else "/api/user/amount")
    if tiers:
        return tiers, {"status": "captured", "source": source, "message": f"登录态充值/订阅接口抓取到 {len(tiers)} 条"}
    if amount_options or amount_results or plan_entry is not None:
        return [], {"status": "empty", "source": source, "message": "登录态充值/订阅接口返回空列表"}
    return [], {"status": "missing", "source": public_source_text(probe.get("_probePath") or probe_location(probe)), "message": "live auth probe 尚未包含 New API 充值接口"}


def v1_plan_rows_from_probe(probe: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    plan_sources: list[Any] = []
    plan_entry = find_probe_result(probe, "/api/v1/payment/plans")
    checkout_entry = find_probe_result(probe, "/api/v1/payment/checkout-info")
    checkout_data = probe_result_data_from_entry(checkout_entry)
    if isinstance(checkout_data, dict):
        plan_sources.append(checkout_data.get("plans"))
    plan_sources.append(probe_result_data_from_entry(plan_entry))
    for source in plan_sources:
        plan_rows, _found = extract_collection(source)
        for item in plan_rows:
            if not isinstance(item, dict):
                continue
            plan = dict(item.get("plan") if isinstance(item.get("plan"), dict) else item)
            title = sanitize_public_text(plan.get("title") or plan.get("name") or plan.get("product_name") or "subscription plan")
            price = parse_float(plan.get("price") or plan.get("amount") or plan.get("rmbAmount") or plan.get("rmb_amount") or plan.get("price_amount"))
            usd_amount = parse_float(plan.get("usdAmount") or plan.get("usd_amount") or plan.get("usd"))
            if usd_amount is None:
                for key in ("monthly_limit_usd", "weekly_limit_usd", "daily_limit_usd"):
                    usd_amount = parse_float(plan.get(key))
                    if usd_amount is not None:
                        if key == "daily_limit_usd":
                            usd_amount *= parse_float(plan.get("validity_days")) or 1
                        elif key == "weekly_limit_usd":
                            usd_amount *= max(1, int((parse_float(plan.get("validity_days")) or 7) // 7))
                        break
            if usd_amount is None:
                usd_amount = convert_quota_to_usd(plan.get("total_amount") or plan.get("quota"))
            if usd_amount is None:
                match = re.search(r"(?:\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:USD|usd|刀|美元|\$))", str(plan.get("description") or ""))
                if match:
                    usd_amount = parse_float(match.group(1) or match.group(2))
            key = (title, price, usd_amount, plan.get("group_name") or plan.get("upgrade_group") or plan.get("id"))
            if key in seen:
                continue
            seen.add(key)
            if price is None or usd_amount is None:
                continue
            plan["title"] = title
            plan["price_amount"] = price
            plan["usd_amount"] = usd_amount
            rows.append(plan)
    return rows


def krill_shop_payloads(probe: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    payloads: list[tuple[str, dict[str, Any]]] = []
    for path in ("/api/public/shop/products", "/api/plans"):
        entry = find_probe_result(probe, path)
        body = probe_result_body_from_entry(entry)
        if isinstance(body, dict):
            payloads.append((path, body))
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
    if parse_bool(plan.get("is_custom")) or parse_bool(plan.get("custom")):
        return False
    if "is_on_sale" in plan and not parse_bool(plan.get("is_on_sale")):
        return False
    allowed_provider_ids = plan.get("allowed_provider_ids")
    if isinstance(allowed_provider_ids, list) and 1 not in {parse_int(item) for item in allowed_provider_ids}:
        return False
    billing_type = sanitize_public_text(plan.get("billing_type") or plan.get("billingType"))
    if billing_type != "usd_daily":
        return False
    price = parse_float(plan.get("price_usd_per_month") or plan.get("price"))
    daily_quota = parse_float(plan.get("daily_quota_usd"))
    duration_days = parse_float(plan.get("duration_days"))
    if price is None or daily_quota is None or duration_days is None:
        return False
    if price <= 0 or daily_quota <= 0 or duration_days <= 0 or price >= 10000:
        return False
    name = sanitize_public_text(plan.get("name") or plan.get("title"))
    if any(marker in name for marker in ("企业", "定制", "测试", "推广", "内部")):
        return False
    return True


def krill_codex_plan_row(plan: dict[str, Any], recharge_location: str) -> dict[str, Any] | None:
    price = parse_float(plan.get("price_usd_per_month") or plan.get("price"))
    daily_quota = parse_float(plan.get("daily_quota_usd"))
    duration_days = parse_float(plan.get("duration_days"))
    if price is None or daily_quota is None or duration_days is None:
        return None
    route_keys = plan.get("entry_route_keys")
    route_note = ""
    if isinstance(route_keys, list) and route_keys:
        route_note = "; entry routes " + ", ".join(sanitize_public_text(item) for item in route_keys if sanitize_public_text(item))
    return normalize_recharge_row(
        {
            "rechargeName": plan.get("name") or plan.get("title") or "Krill Codex package",
            "billingType": billing_type_from_days(duration_days),
            "rmbAmount": price,
            "usdAmount": daily_quota * duration_days,
            "rechargeLocation": recharge_location,
            "expiresRule": f"{format_plain_number(duration_days)} day package; total quota from {format_plain_number(daily_quota)} USD/day; Codex package{route_note}",
        }
    )


def krill_balance_product_row(product: dict[str, Any], recharge_location: str) -> dict[str, Any] | None:
    name = sanitize_public_text(product.get("name") or product.get("title") or "Krill balance topup")
    if "负余额" in name or "仅限" in name:
        return None
    rmb_amount = parse_float(product.get("price_cny") or product.get("price") or product.get("rmbAmount"))
    usd_amount = parse_float(product.get("amount_usd") or product.get("usdAmount") or product.get("usd"))
    if rmb_amount is None or usd_amount is None or rmb_amount <= 0 or usd_amount <= 0:
        return None
    return normalize_recharge_row(
        {
            "rechargeName": name,
            "billingType": "permanent",
            "rmbAmount": rmb_amount,
            "usdAmount": usd_amount,
            "rechargeLocation": recharge_location,
            "expiresRule": "Balance top-up; no expiry shown on shop page",
        }
    )


def krill_recharge_rows_from_payload(payload: dict[str, Any], source_label: str) -> list[dict[str, Any]]:
    tiers: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for plan in krill_plan_rows(payload):
        if not krill_plan_is_visible_codex(plan):
            continue
        row = krill_codex_plan_row(plan, f"{source_label} Codex package")
        if row and recharge_row_key(row) not in seen:
            seen.add(recharge_row_key(row))
            tiers.append(row)
    for product in krill_balance_product_rows(payload):
        row = krill_balance_product_row(product, f"{source_label} balance tab")
        if row and recharge_row_key(row) not in seen:
            seen.add(recharge_row_key(row))
            tiers.append(row)
    return tiers


def krill_live_probe_recharge_rows(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]] | None:
    payloads = krill_shop_payloads(probe)
    if not payloads:
        return None
    tiers: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for path, payload in payloads:
        source_label = "Krill public shop products API" if path == "/api/public/shop/products" else "Krill plans API"
        for row in krill_recharge_rows_from_payload(payload, source_label):
            key = (row.get("rechargeName"), row.get("billingType"), row.get("rmbAmount"), row.get("usdAmount"))
            if key in seen:
                continue
            seen.add(key)
            tiers.append(row)
    source_path = "/api/public/shop/products" if find_probe_result(probe, "/api/public/shop/products") is not None else "/api/plans"
    source = probe_source_url(probe, source_path)
    if tiers:
        return tiers, {"status": "captured", "source": source, "message": f"Krill 商店接口抓取到 {len(tiers)} 条充值/套餐档位"}
    if any(entry_is_blocked(find_probe_result(probe, path)) for path, _payload in payloads):
        return [], {"status": "blocked", "source": source, "message": "Krill 商店接口被验证码或风控阻断"}
    return [], {"status": "empty", "source": source, "message": "Krill 商店接口可访问，但没有可归档的公开充值/套餐档位"}


def live_probe_recharge_rows(probe: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    krill_result = krill_live_probe_recharge_rows(probe)
    if krill_result is not None:
        return krill_result
    new_api_result = new_api_recharge_rows(probe)
    if new_api_result is not None:
        return new_api_result
    tiers: list[dict[str, Any]] = []
    plan_entry = find_probe_result(probe, "/api/v1/payment/plans")
    for item in v1_plan_rows_from_probe(probe):
        if not isinstance(item, dict):
            continue
        plan = item
        title = sanitize_public_text(plan.get("title") or plan.get("name") or "subscription plan")
        price = parse_float(plan.get("price_amount") or plan.get("price") or plan.get("amount") or plan.get("rmbAmount") or plan.get("rmb_amount"))
        usd_amount = parse_float(plan.get("usd_amount") or plan.get("usdAmount") or plan.get("usd"))
        row = normalize_recharge_row(
            {
                "rechargeName": title,
                "billingType": (
                    plan.get("billing_type")
                    or (
                        billing_type_from_days(plan.get("validity_days"))
                        if plan.get("validity_days")
                        else duration_unit_to_billing_type(plan.get("duration_unit") or plan.get("validity_unit"))
                    )
                ),
                "rmbAmount": price,
                "usdAmount": usd_amount,
                "rechargeLocation": "login probe payment plans API",
                "expiresRule": plan_expires_rule(plan),
            }
        )
        if row:
            tiers.append(row)

    config_entry = find_probe_result(probe, "/api/v1/payment/config")
    checkout_entry = find_probe_result(probe, "/api/v1/payment/checkout-info")
    payment_config = probe_result_data_from_entry(config_entry)
    checkout_info = probe_result_data_from_entry(checkout_entry)
    public_settings = probe_result_data_from_entry(find_probe_result(probe, "/api/v1/settings/public"))
    payment_config = payment_config if isinstance(payment_config, dict) else {}
    checkout_info = checkout_info if isinstance(checkout_info, dict) else {}
    public_settings = public_settings if isinstance(public_settings, dict) else {}
    recharge_multiplier = (
        parse_float(checkout_info.get("balance_recharge_multiplier"))
        or parse_float(payment_config.get("balance_recharge_multiplier"))
        or 0.0
    )
    balance_disabled = bool(checkout_info.get("balance_disabled", payment_config.get("balance_disabled")))
    quick_amounts = probe.get("quick_amounts") if isinstance(probe.get("quick_amounts"), list) else []
    wallet_enabled = (
        not explicitly_false(payment_config.get("enabled"))
        and not explicitly_false(checkout_info.get("enabled"))
        and not explicitly_false(public_settings.get("payment_enabled"))
        and recharge_multiplier > 0
        and not balance_disabled
    )
    if wallet_enabled and quick_amounts:
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
    return [], {"status": "missing", "source": public_source_text(probe.get("_probePath") or probe_location(probe)), "message": "live auth probe 尚未包含支付接口"}


def merge_announcements(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for item in existing + incoming:
        normalized_content = normalize_announcement_markdown(item.get("content"))
        fingerprint = announcement_dedupe_fingerprint(item.get("content"))
        key = (
            str(item.get("id") or ""),
            str(item.get("publishedAt") or ""),
            fingerprint,
        )
        normalized_item = dict(item)
        if normalized_content and normalized_content != str(item.get("content") or ""):
            normalized_item["content"] = normalized_content
        content_html = str(item.get("contentHtml") or "").strip()
        if content_html:
            normalized_item["contentHtml"] = content_html

        current = merged_map.get(key)
        if current is None:
            merged_map[key] = normalized_item
            order.append(key)
            continue

        current_score = announcement_quality_score(current, normalize_announcement_markdown(current.get("content")))
        next_score = announcement_quality_score(normalized_item, normalized_content)
        if next_score > current_score:
            merged_map[key] = normalized_item

    return [merged_map[key] for key in order]


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


def probe_login_block_status(probe: dict[str, Any], *, message: str) -> dict[str, str] | None:
    if not isinstance(probe, dict):
        return None
    capture = probe.get("announcementCapture")
    if not isinstance(capture, dict):
        return None

    if capture.get("loginBlocked") is True:
        path = sanitize_public_text(capture.get("blockPath") or "/api/v1/auth/login")
        source = probe_location(probe).rstrip("/") + path if path.startswith("/") else probe_location(probe)
        return {
            "status": "blocked",
            "source": sanitize_public_text(source),
            "message": message,
        }

    attempts = capture.get("loginAttempts")
    if not isinstance(attempts, list):
        return None
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        attempt_text = json.dumps(attempt, ensure_ascii=False).lower()
        if any(marker in attempt_text for marker in ("turnstile", "captcha", "验证码", "人机验证", "风控")):
            path = sanitize_public_text(attempt.get("path") or "/api/v1/auth/login")
            source = probe_location(probe).rstrip("/") + path if path.startswith("/") else probe_location(probe)
            return {
                "status": "blocked",
                "source": sanitize_public_text(source),
                "message": message,
            }
    return None


def public_probe_root_status(public_probe: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(public_probe, dict):
        return None
    results = public_probe.get("results")
    if not isinstance(results, dict):
        return None
    root_entry = results.get("/")
    if not isinstance(root_entry, dict):
        return None

    source = sanitize_public_text(root_entry.get("url") or public_probe.get("baseUrl") or public_probe.get("base_url"))
    status_code = int(root_entry.get("status") or 0)
    if status_code == 404:
        return {
            "status": "failed",
            "source": source,
            "message": "当前站点入口返回 HTTP 404；历史样本仍保留，但当前入口已失效或不可访问。",
        }
    if status_code >= 500:
        return {
            "status": "failed",
            "source": source,
            "message": f"当前站点入口返回 HTTP {status_code}；历史样本仍保留，但当前入口暂不可访问。",
        }
    error_text = normalize_public_text(root_entry.get("error"))
    if error_text:
        return {
            "status": "failed",
            "source": source,
            "message": f"当前站点入口探测失败：{error_text}",
        }
    return None


def load_live_probe_snapshots(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for station_key, probe in load_live_auth_probes(station_aliases).items():
        stored_announcements = normalized_announcement_rows(probe.get("mergedAnnouncements"))
        announcements, announcement_status = live_probe_announcements_and_status(station_key, probe)
        if announcements:
            announcements = merge_announcements(stored_announcements, announcements)
        elif stored_announcements:
            announcements = stored_announcements
        groups, group_status = live_probe_group_rows(probe)
        recharges, recharge_status = live_probe_recharge_rows(probe)
        station_shop_snapshot = known_station_pay_shop_snapshot(station_key)
        station_type_hint = ""
        if station_shop_snapshot:
            station_type_hint = sanitize_public_text(station_shop_snapshot.get("stationTypeHint"))
            shop_recharges = normalized_recharge_rows(station_shop_snapshot.get("rechargeTiers"))
            if shop_recharges:
                recharges = shop_recharges
                recharge_status = {
                    "status": "captured",
                    "source": public_source_text(station_shop_snapshot.get("sourceUrl")),
                    "message": f"官方外部店铺核验到 {len(recharges)} 条充值/套餐档位",
                }
        if not station_type_hint:
            station_type_hint = infer_station_type_from_recharge_tiers(recharges)
        announcement_status = normalize_live_probe_status(announcement_status)
        group_status = normalize_live_probe_status(group_status)
        recharge_status = normalize_live_probe_status(recharge_status)
        snapshots[station_key] = {
            "announcements": announcements,
            "groupMultipliers": groups,
            "rechargeTiers": recharges,
            "stationTypeHint": station_type_hint,
            "verifiedTierCount": live_probe_verified_tier_count(groups, recharges),
            "evidenceStatus": {
                "announcements": announcement_status,
                "groupMultipliers": group_status,
                "rechargeTiers": recharge_status,
            },
            "sourceUrl": probe_location(probe),
            "rawProbe": probe,
        }
    return snapshots


def normalize_group_row(item: dict[str, Any]) -> dict[str, Any] | None:
    group_name = sanitize_public_text(item.get("groupName") or item.get("group_name"))
    group_multiplier = parse_float(item.get("groupMultiplier") if "groupMultiplier" in item else item.get("group_multiplier"))
    if not group_name or group_multiplier is None:
        return None
    row: dict[str, Any] = {
        "groupName": group_name,
        "groupMultiplier": group_multiplier,
    }
    codex_eligible = parse_optional_bool(
        item.get("codexEligible") if "codexEligible" in item else item.get("codex_eligible")
    )
    if codex_eligible is not None:
        row["codexEligible"] = codex_eligible
    usage_label = sanitize_public_text(item.get("usageLabel") or item.get("usage_label"))
    if usage_label:
        row["usageLabel"] = usage_label
    return row


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
    display_only = parse_bool(item.get("displayOnly") or item.get("display_only"))
    if not recharge_name or rmb_amount is None or (usd_amount is None and not display_only):
        return None
    recharge_location = sanitize_public_text(item.get("rechargeLocation") or item.get("recharge_location") or item.get("location"))
    expires_rule = sanitize_public_text(item.get("expiresRule") or item.get("expires_rule") or item.get("note"))
    row: dict[str, Any] = {
        "rechargeName": recharge_name,
        "billingType": billing_type,
        "billingTypeLabel": sanitize_public_text(item.get("billingTypeLabel") or item.get("billing_type_label")) or BILLING_LABELS.get(billing_type, billing_type or "未知"),
        "rmbAmount": rmb_amount,
        "usdAmount": usd_amount,
        "rechargeLocation": recharge_location,
        "expiresRule": expires_rule,
    }
    if display_only:
        row["displayOnly"] = True
    payment_currency = sanitize_public_text(item.get("paymentCurrency") or item.get("payment_currency"))
    payment_amount = parse_float(item.get("paymentAmount") if "paymentAmount" in item else item.get("payment_amount"))
    if payment_currency:
        row["paymentCurrency"] = payment_currency.upper()
    if payment_amount is not None:
        row["paymentAmount"] = payment_amount
    return row


def group_row_key(group: dict[str, Any]) -> tuple[str, float]:
    return (str(group.get("groupName", "")), float(group.get("groupMultiplier", 0.0)))


def recharge_row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("rechargeName", ""),
        row.get("billingType", ""),
        row.get("rmbAmount"),
        row.get("usdAmount"),
        row.get("paymentCurrency", ""),
        row.get("paymentAmount"),
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


def normalized_group_rows(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    if not isinstance(rows, list):
        return normalized
    for item in rows:
        if not isinstance(item, dict):
            continue
        group = normalize_group_row(item)
        if not group:
            continue
        key = group_row_key(group)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(group)
    return normalized


def normalized_recharge_rows(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    if not isinstance(rows, list):
        return normalized
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = normalize_recharge_row(item)
        if not row:
            continue
        key = recharge_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(row)
    return normalized


def infer_station_type_from_recharge_tiers(recharge_tiers: Any) -> str:
    normalized = normalized_recharge_rows(recharge_tiers)
    if not normalized:
        return ""
    billing_types = {row.get("billingType") for row in normalized}
    has_package_tiers = any(billing_type in PACKAGE_BILLING_TYPES for billing_type in billing_types)
    has_permanent_tiers = "permanent" in billing_types
    if has_package_tiers and has_permanent_tiers:
        return "mixed"
    if has_package_tiers:
        return "subscription"
    return "non_subscription"


def live_probe_verified_tier_count(group_rows: Any, recharge_tiers: Any) -> int:
    if not normalized_group_rows(group_rows):
        return 0
    valid_recharges = [
        row
        for row in normalized_recharge_rows(recharge_tiers)
        if row.get("rmbAmount") is not None
        and row.get("usdAmount") is not None
        and parse_float(row.get("rmbAmount")) is not None
        and parse_float(row.get("usdAmount")) is not None
        and (parse_float(row.get("usdAmount")) or 0) > 0
    ]
    return len(valid_recharges)


def normalized_tier_note_segments(value: Any) -> list[str]:
    note = normalize_public_text(value)
    if not note:
        return []
    return [
        segment.strip()
        for segment in re.split(r";\s+", note)
        if segment.strip()
    ]


def collapse_legacy_tier_note_fragments(notes: list[str]) -> list[str]:
    collapsed: list[str] = []
    for note in notes:
        if (
            collapsed
            and collapsed[-1].startswith("Public marketing page conversion sample:")
            and (
                note in {"not a fixed package", "expiry not stated"}
                or re.fullmatch(r"minimum recharge \d+(?:\.\d+)? RMB", note)
            )
        ):
            if note not in normalized_tier_note_segments(collapsed[-1]):
                collapsed[-1] = f"{collapsed[-1]}; {note}"
            continue
        collapsed.append(note)
    return collapsed


def normalized_tier_notes(rows: Any) -> list[str]:
    normalized: list[str] = []
    seen_segments: set[str] = set()
    if not isinstance(rows, list):
        return normalized
    for item in rows:
        note_segments: list[str] = []
        for note in normalized_tier_note_segments(item):
            if note and note not in seen_segments:
                seen_segments.add(note)
                note_segments.append(note)
        if note_segments:
            normalized.append("; ".join(note_segments))
    return collapse_legacy_tier_note_fragments(normalized)


def normalized_announcement_rows(rows: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return normalized
    for item in rows:
        if not isinstance(item, dict):
            continue
        content = normalize_announcement_text(item.get("content"))
        if not content:
            continue
        normalized.append(
            {
                "id": str(item.get("id") or f"existing-{len(normalized) + 1}"),
                "publishedAt": str(item.get("publishedAt") or ""),
                "type": normalize_announcement_text(item.get("type") or "default"),
                "extra": normalize_announcement_text(item.get("extra") or ""),
                "content": content,
                **({"contentHtml": str(item.get("contentHtml") or "").strip()} if str(item.get("contentHtml") or "").strip() else {}),
                "sourceUrl": sanitize_public_text(item.get("sourceUrl")),
            }
        )
    return normalized


def merge_tier_notes(station: dict[str, Any], notes: Any) -> None:
    for note in normalized_tier_notes(notes):
        if note not in station["tierNotes"]:
            station["tierNotes"].append(note)


def dedupe_station_tier_notes(stations: dict[str, dict[str, Any]]) -> None:
    for station in stations.values():
        station["tierNotes"] = normalized_tier_notes(station.get("tierNotes"))


def load_postgres_base_site_snapshot(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    if not postgres_base_merge_enabled():
        return {}
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return {}

    try:
        import psycopg
    except ImportError:
        return {}

    try:
        with psycopg.connect(database_url) as con:
            with con.cursor() as cur:
                cur.execute(
                    """
                    select payload
                    from site_data_snapshots
                    where status = 'success'
                      and payload is not null
                    order by created_at desc, id desc
                    limit 1
                    """
                )
                row = cur.fetchone()
    except Exception:
        return {}

    if not row or not isinstance(row[0], dict):
        return {}

    baseline: dict[str, dict[str, Any]] = {}
    for raw_station in row[0].get("stations", []):
        if not isinstance(raw_station, dict):
            continue
        station_key = canonical_station_key(raw_station.get("key"), station_aliases)
        if not station_key or not is_public_station_key(station_key):
            continue
        baseline[station_key] = raw_station
    return baseline


def apply_postgres_base_station_records(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    baseline: dict[str, dict[str, Any]],
    *,
    station_aliases: dict[str, str] | None = None,
    preserved_station_keys: set[str] | None = None,
) -> None:
    preserved_station_keys = {canonical_station_key(key, station_aliases) for key in (preserved_station_keys or set())}
    for station_key, raw_station in baseline.items():
        station_url = sanitize_public_text(raw_station.get("url"))
        if not is_public_station_url(station_url):
            continue

        if station_key in stations:
            merge_baseline_station_record(
                stations[station_key],
                station_urls,
                station_key,
                raw_station,
                station_url,
                station_aliases=station_aliases,
            )
            continue

        target_station_key = ""
        if station_key not in preserved_station_keys:
            target_station_key = find_station_key_by_url_host(stations, station_urls, station_url)
        if target_station_key:
            merge_baseline_station_record(
                stations[target_station_key],
                station_urls,
                target_station_key,
                raw_station,
                station_url,
                station_aliases=station_aliases,
            )
            continue

        station = ensure_station(
            stations,
            station_key,
            station_aliases=station_aliases,
            label=raw_station.get("label", ""),
            url=station_url,
            station_type=raw_station.get("stationType", ""),
            platform_guess=raw_station.get("platformGuess", ""),
        )
        station["verifiedTierCount"] = parse_int(raw_station.get("verifiedTierCount"))
        station["groupMultipliers"] = normalized_group_rows(raw_station.get("groupMultipliers"))
        station["rechargeTiers"] = normalized_recharge_rows(raw_station.get("rechargeTiers"))
        station["tierNotes"] = normalized_tier_notes(raw_station.get("tierNotes"))
        station["announcements"] = normalized_announcement_rows(raw_station.get("announcements"))
        if isinstance(raw_station.get("quality"), dict):
            station["quality"] = deepcopy(raw_station["quality"])
        if raw_station.get("audits"):
            station["audits"] = deepcopy(raw_station["audits"])
        add_exact_station_url(station_urls, station_key, station_url, station_aliases)
        for announcement in station.get("announcements", []):
            source_url = sanitize_public_text(announcement.get("sourceUrl"))
            if source_url:
                add_station_url(station_urls, station_key, source_url, station_aliases)


def merge_baseline_station_record(
    station: dict[str, Any],
    station_urls: dict[str, set[str]],
    station_key: str,
    raw_station: dict[str, Any],
    station_url: str,
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    existing_url = sanitize_public_text(station.get("url"))
    if not existing_url:
        station["url"] = station_url

    label = sanitize_public_text(raw_station.get("label"))
    current_label = sanitize_public_text(station.get("label"))
    default_labels = {
        station_key,
        station_display_label(station_key, "", existing_url),
        station_display_label(station_key, station_key, existing_url),
        station_display_label(station_key, "", ""),
        station_display_label(station_key, station_key, ""),
    }
    if label and (not current_label or current_label in default_labels):
        station["label"] = station_display_label(station_key, label, station.get("url"))

    station_type = sanitize_public_text(raw_station.get("stationType"))
    if station_type and sanitize_public_text(station.get("stationType")) in {"", "unknown_pending"}:
        station["stationType"] = station_type
        station["stationTypeLabel"] = FULL_TYPE_LABELS.get(station_type, station_type)
        station["stationTypeShortLabel"] = SHORT_TYPE_LABELS.get(station_type, station_type)

    platform_guess = sanitize_public_text(raw_station.get("platformGuess"))
    if platform_guess and not station.get("platformGuess"):
        station["platformGuess"] = platform_guess

    verified_tier_count = parse_int(raw_station.get("verifiedTierCount"))
    if verified_tier_count and not parse_int(station.get("verifiedTierCount")):
        station["verifiedTierCount"] = verified_tier_count

    if not station.get("groupMultipliers") and raw_station.get("groupMultipliers"):
        station["groupMultipliers"] = normalized_group_rows(raw_station.get("groupMultipliers"))
    if not station.get("rechargeTiers") and raw_station.get("rechargeTiers"):
        station["rechargeTiers"] = normalized_recharge_rows(raw_station.get("rechargeTiers"))

    station.setdefault("tierNotes", [])
    for note in normalized_tier_notes(raw_station.get("tierNotes")):
        if note not in station["tierNotes"]:
            station["tierNotes"].append(note)

    station["announcements"] = merge_announcements(
        station.get("announcements", []),
        normalized_announcement_rows(raw_station.get("announcements")),
    )
    station.setdefault("quality", {})
    if isinstance(raw_station.get("quality"), dict):
        for window_key, quality_payload in raw_station["quality"].items():
            if not isinstance(quality_payload, dict):
                continue
            if isinstance(station["quality"].get(window_key), dict):
                continue
            station["quality"][window_key] = deepcopy(quality_payload)
    if raw_station.get("audits") and not station.get("audits"):
        station["audits"] = deepcopy(raw_station["audits"])

    add_exact_station_url(station_urls, station_key, station_url, station_aliases)
    for announcement in station.get("announcements", []):
        source_url = sanitize_public_text(announcement.get("sourceUrl"))
        if source_url:
            add_station_url(station_urls, station_key, source_url, station_aliases)


def load_existing_detail_baseline(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    if not SITE_DATA_PATH.exists():
        return {}
    try:
        existing = read_existing_site_data()
    except (OSError, json.JSONDecodeError):
        return {}

    baseline: dict[str, dict[str, Any]] = {}
    for raw_station in existing.get("stations", []):
        if not isinstance(raw_station, dict):
            continue
        station_key = canonical_station_key(raw_station.get("key"), station_aliases)
        if not station_key or not is_public_station_key(station_key):
            continue
        baseline[station_key] = {
            "groupMultipliers": normalized_group_rows(raw_station.get("groupMultipliers")),
            "rechargeTiers": normalized_recharge_rows(raw_station.get("rechargeTiers")),
            "tierNotes": normalized_tier_notes(raw_station.get("tierNotes")),
            "announcements": normalized_announcement_rows(raw_station.get("announcements")),
        }
    return baseline


def load_existing_station_records(station_aliases: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    if not SITE_DATA_PATH.exists():
        return {}
    try:
        existing = read_existing_site_data()
    except (OSError, json.JSONDecodeError):
        return {}

    baseline: dict[str, dict[str, Any]] = {}
    for raw_station in existing.get("stations", []):
        if not isinstance(raw_station, dict):
            continue
        station_key = canonical_station_key(raw_station.get("key"), station_aliases)
        if not station_key or not is_public_station_key(station_key):
            continue
        baseline[station_key] = raw_station
    return baseline


def apply_existing_detail_baseline(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    baseline: dict[str, dict[str, Any]],
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    for station_key, station in stations.items():
        existing = baseline.get(station_key)
        if not existing:
            continue
        if not station.get("groupMultipliers") and existing.get("groupMultipliers"):
            station["groupMultipliers"] = deepcopy(existing["groupMultipliers"])
        if not station.get("rechargeTiers") and existing.get("rechargeTiers"):
            station["rechargeTiers"] = deepcopy(existing["rechargeTiers"])
        if not station.get("tierNotes") and existing.get("tierNotes"):
            station["tierNotes"] = list(existing["tierNotes"])
        if existing.get("announcements"):
            station["announcements"] = merge_announcements(existing["announcements"], station.get("announcements", []))
            for announcement in station["announcements"]:
                source_url = sanitize_public_text(announcement.get("sourceUrl"))
                if source_url:
                    add_station_url(station_urls, station_key, source_url, station_aliases)


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
            row["label"] = station_display_label(row.get("station"), row.get("label"), row.get("stationUrl"))
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
        raw_label = station_display_label(station_key, raw_station.get("label"), raw_station.get("url"))
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


def multiplier_tier_row_groups(
    rows: list[dict[str, str]],
    *,
    station_aliases: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        station_key = canonical_station_key(row.get("station", ""), station_aliases)
        if not is_public_station_key(station_key):
            continue
        bucket = grouped.setdefault(
            station_key,
            {
                "groupMultipliers": [],
                "rechargeTiers": [],
            },
        )
        group = normalize_group_row({"group_name": row.get("group_name"), "group_multiplier": row.get("group_multiplier")})
        if group:
            bucket["groupMultipliers"].append(group)
        recharge = normalize_recharge_row(
            {
                "recharge_name": row.get("recharge_name"),
                "billing_type": row.get("billing_type"),
                "billing_type_label": BILLING_LABELS.get(row.get("billing_type", ""), sanitize_public_text(row.get("billing_type") or "鏈煡")),
                "rmb_amount": row.get("rmb_amount"),
                "usd_amount": row.get("usd_amount"),
                "recharge_location": row.get("recharge_location"),
                "expires_rule": row.get("expires_rule"),
            }
        )
        if recharge:
            bucket["rechargeTiers"].append(recharge)
    return grouped


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
            row["label"] = station_display_label(station.get("key"), station.get("label"), station.get("url"))
            row["stationUrl"] = sanitize_public_text(station.get("url"))
            row["stationType"] = station.get("stationType", "")
            row["stationTypeLabel"] = station.get("stationTypeLabel", "")
            row["stationTypeShortLabel"] = station.get("stationTypeShortLabel", "")

    for station in stations.values():
        for row in station.get("quality", {}).values():
            if not isinstance(row, dict):
                continue
            row["station"] = station["key"]
            row["label"] = station_display_label(station.get("key"), station.get("label"), station.get("url"))
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


def public_subscription_plan_features_text(plan: dict[str, Any], separator: str = " ") -> str:
    features = plan.get("features")
    if not isinstance(features, list):
        return ""
    return separator.join(sanitize_public_text(item) for item in features if sanitize_public_text(item))


def looks_like_subscription_plan(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    if "plan" in plan and isinstance(plan.get("plan"), dict):
        plan = plan["plan"]
    has_price = any(key in plan for key in ("price", "price_amount", "rmbAmount", "rmb_amount", "price_cny", "cny_amount"))
    has_credit = any(
        key in plan
        for key in (
            "usd_amount",
            "usdAmount",
            "usd",
            "amount_usd",
            "charge_price",
            "quota_amount",
            "amount",
            "total_amount",
            "quota",
            "daily_limit_usd",
            "weekly_limit_usd",
            "monthly_limit_usd",
        )
    )
    text = " ".join(
        str(value or "")
        for value in (
            plan.get("name"),
            plan.get("title"),
            plan.get("description"),
            plan.get("duration"),
            public_subscription_plan_features_text(plan),
        )
    ).lower()
    return has_price and (has_credit or "$" in text or "usd" in text)


def public_subscription_plan_price(plan: dict[str, Any]) -> float | None:
    return parse_float(
        plan.get("price_amount")
        or plan.get("price")
        or plan.get("rmbAmount")
        or plan.get("rmb_amount")
        or plan.get("price_cny")
        or plan.get("cny_amount")
    )


def public_subscription_plan_usd_amount(plan: dict[str, Any]) -> float | None:
    direct = plan_total_usd(plan)
    if direct and direct > 0:
        return direct
    feature_text = public_subscription_plan_features_text(plan)
    text = " ".join(str(value or "") for value in (plan.get("description"), plan.get("subtitle"), plan.get("desc"), feature_text))
    match = re.search(r"(?:\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:USD|usd|\$))", text)
    if match:
        return parse_float(match.group(1) or match.group(2))
    return None


def public_subscription_plan_billing_type(plan: dict[str, Any]) -> str:
    duration = sanitize_public_text(plan.get("duration")).lower()
    feature_text = public_subscription_plan_features_text(plan).lower()
    if any(marker in f"{duration} {feature_text}" for marker in ("one-time", "onetime", "permanent", "一次性", "永久")):
        return "permanent"
    return plan_billing_type(plan)


def public_subscription_plan_expires_rule(plan: dict[str, Any]) -> str:
    duration = sanitize_public_text(plan.get("duration"))
    feature_text = public_subscription_plan_features_text(plan, "; ")
    combined = f"{duration} {feature_text}".lower()
    if any(marker in combined for marker in ("one-time", "onetime", "permanent", "一次性", "永久")):
        return "One-time recharge; permanent balance"
    return plan_expires_rule(plan)


def public_subscription_plan_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    plan_sources: list[Any] = []
    for key in (
        "subscription_plans_payload",
        "subscriptionPlansPayload",
        "subscription_plans",
        "subscriptionPlans",
    ):
        if key in payload:
            plan_sources.append(payload.get(key))

    source_url = sanitize_public_text(payload.get("source_url") or payload.get("sourceUrl"))
    top_level_rows, top_level_found = extract_collection(payload)
    if top_level_found and (source_url.rstrip("/").endswith("/api/subscription/plans") or any(isinstance(item, dict) and looks_like_subscription_plan(item) for item in top_level_rows)):
        plan_sources.append(payload)

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for source in plan_sources:
        plan_rows, _found = extract_collection(source)
        for item in plan_rows:
            if not isinstance(item, dict):
                continue
            plan = dict(item.get("plan") if isinstance(item.get("plan"), dict) else item)
            if explicitly_false(plan.get("enabled")) or not looks_like_subscription_plan(plan):
                continue
            title = sanitize_public_text(plan.get("title") or plan.get("name") or plan.get("product_name") or "subscription plan")
            price = public_subscription_plan_price(plan)
            usd_amount = public_subscription_plan_usd_amount(plan)
            key = (plan.get("id"), title, price, usd_amount)
            if key in seen:
                continue
            seen.add(key)
            row = normalize_recharge_row(
                {
                    "rechargeName": title,
                    "billingType": public_subscription_plan_billing_type(plan),
                    "rmbAmount": price,
                    "usdAmount": usd_amount,
                    "rechargeLocation": "public /api/subscription/plans",
                    "expiresRule": public_subscription_plan_expires_rule(plan),
                }
            )
            if row:
                rows.append(row)
    return rows


def parse_public_pricing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    recharge_tiers: list[dict[str, Any]] = []
    tier_notes: list[str] = []
    source_url = sanitize_public_text(payload.get("server_address") or payload.get("base_url") or payload.get("source_url") or payload.get("sourceUrl"))
    station_type_hint = ""

    normalized_groups = normalized_group_rows(payload.get("groupMultipliers") or payload.get("group_multipliers"))
    if normalized_groups:
        groups.extend(normalized_groups)

    normalized_recharges = normalized_recharge_rows(payload.get("rechargeTiers") or payload.get("recharge_tiers_normalized"))
    if normalized_recharges:
        recharge_tiers.extend(normalized_recharges)

    if "krill-ai.com" in source_url:
        krill_tiers = krill_recharge_rows_from_payload(payload, "Krill public shop products API")
        if krill_tiers:
            recharge_tiers.extend(krill_tiers)
            station_type_hint = "mixed"
            tier_notes.append("Krill shop products API exposes Codex packages and balance top-ups; Codex package page states 0.2x billing for all routes.")

    subscription_plan_rows = public_subscription_plan_rows_from_payload(payload)
    if subscription_plan_rows:
        recharge_tiers.extend(subscription_plan_rows)

    for group_ratio in (
        payload.get("group_ratio"),
        payload.get("groupRatio"),
        (payload.get("data") if isinstance(payload.get("data"), dict) else {}).get("group_ratio"),
    ):
        if isinstance(group_ratio, dict):
            for group_name, raw_value in group_ratio.items():
                group = maybe_parse_group_ratio(group_name, raw_value)
                if group:
                    groups.append(group)

    status_data = payload.get("status_payload") or payload.get("statusPayload")
    if isinstance(status_data, dict) and isinstance(status_data.get("data"), dict):
        status_data = status_data["data"]
    if not isinstance(status_data, dict) and isinstance(payload.get("data"), dict):
        data_payload = payload["data"]
        if any(key in data_payload for key in ("quota_per_unit", "price", "server_address")):
            status_data = data_payload
    if not isinstance(status_data, dict):
        status_data = payload
    price = parse_float(status_data.get("price") if isinstance(status_data, dict) else None)
    quota_per_unit = parse_float(status_data.get("quota_per_unit") if isinstance(status_data, dict) else None)
    if not subscription_plan_rows and price and quota_per_unit and price > 0 and quota_per_unit > 0:
        usd_amount = quota_per_unit / 500000.0
        row = normalize_recharge_row(
            {
                "rechargeName": f"public status {format_plain_number(price)} RMB = {format_plain_number(usd_amount)} USD credit",
                "billingType": "permanent",
                "rmbAmount": price,
                "usdAmount": usd_amount,
                "rechargeLocation": "public /api/status",
                "expiresRule": "Public status price/quota conversion; expiry not stated",
            }
        )
        if row:
            recharge_tiers.append(row)

    for key in ("recharge_tiers", "topup_tiers", "topups", "wallet_topups", "pricing_tiers", "data"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            tier = parse_pricing_tier_item(item)
            if tier:
                recharge_tiers.append(tier)

    for key in ("tierNotes", "tier_notes", "notes"):
        notes = payload.get(key)
        if isinstance(notes, list):
            for item in notes:
                note = normalize_public_text(item)
                if note:
                    tier_notes.append(note)
        else:
            note = normalize_public_text(notes)
            if note:
                tier_notes.append(note)

    note = normalize_public_text(payload.get("message"))
    if note:
        tier_notes.append(note)

    return {
        "groupMultipliers": groups,
        "rechargeTiers": recharge_tiers,
        "tierNotes": tier_notes,
        "sourceUrl": source_url,
        "stationTypeHint": station_type_hint,
    }


KNOWN_PAY_SHOP_PRODUCTS: dict[str, dict[str, Any]] = {
    "WE9ZBUQG": {
        "stationTypeHint": "non_subscription",
        "rechargeLocation": "official external pay.ldxp.cn shop redeem code",
        "tierNotes": [
            "LumiBest wallet topup link points to the official pay.ldxp.cn shop. The shop exposes 10/50/100 RMB payment products but no explicit quota field, so the project policy defaults those products to 1 RMB = 1 USD quota."
        ],
        "products": [
            {"rechargeName": "Lumi API 10 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10, "expiresRule": "External shop redeem code; shop exposes price only, quota defaults to 1 RMB = 1 USD"},
            {"rechargeName": "Lumi API 50 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 50, "usdAmount": 50, "expiresRule": "External shop redeem code; shop exposes price only, quota defaults to 1 RMB = 1 USD"},
            {"rechargeName": "Lumi API 100 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 100, "usdAmount": 100, "expiresRule": "External shop redeem code; shop exposes price only, quota defaults to 1 RMB = 1 USD"},
        ],
    },
    "JVDCG8IG": {
        "stationTypeHint": "non_subscription",
        "rechargeLocation": "official external pay.ldxp.cn shop redeem code",
        "tierNotes": [
            "laodog/dogcoding payment config is disabled; recharge evidence uses the official menu-linked external shop redeem-code products."
        ],
        "products": [
            {"rechargeName": "20 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 6, "usdAmount": 20, "expiresRule": "External shop redeem code; permanent balance"},
            {"rechargeName": "30 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 9, "usdAmount": 30, "expiresRule": "External shop redeem code; permanent balance"},
            {"rechargeName": "50 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 15, "usdAmount": 50, "expiresRule": "External shop redeem code; permanent balance"},
            {"rechargeName": "100 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 30, "usdAmount": 100, "expiresRule": "External shop redeem code; permanent balance"},
            {"rechargeName": "200 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 60, "usdAmount": 200, "expiresRule": "External shop redeem code; permanent balance"},
            {"rechargeName": "500 USD external shop redeem code", "billingType": "permanent", "rmbAmount": 145, "usdAmount": 500, "expiresRule": "External shop redeem code; permanent balance"},
        ],
    },
    "u3u": {
        "stationTypeHint": "mixed",
        "rechargeLocation": "official external pay.ldxp.cn shop redeem code",
        "tierNotes": [
            "u3u public menu points to the external shop; product names state package validity and quota, and shop description says quota follows the official 1:1 standard."
        ],
        "products": [
            {"rechargeName": "weekly card 300 USD quota", "billingType": "weekly", "rmbAmount": 28, "usdAmount": 300, "expiresRule": "7 day external shop redeem code package"},
            {"rechargeName": "weekly card 500 USD quota", "billingType": "weekly", "rmbAmount": 48, "usdAmount": 500, "expiresRule": "7 day external shop redeem code package"},
            {"rechargeName": "monthly card 1200 USD quota", "billingType": "monthly", "rmbAmount": 88, "usdAmount": 1200, "expiresRule": "30 day external shop redeem code package"},
            {"rechargeName": "monthly card 2500 USD quota", "billingType": "monthly", "rmbAmount": 178, "usdAmount": 2500, "expiresRule": "30 day external shop redeem code package"},
            {"rechargeName": "monthly card 5000 USD quota", "billingType": "monthly", "rmbAmount": 358, "usdAmount": 5000, "expiresRule": "30 day external shop redeem code package"},
            {"rechargeName": "quarterly card 10000 USD quota", "billingType": "quarterly", "rmbAmount": 588, "usdAmount": 10000, "expiresRule": "90 day external shop redeem code package"},
            {"rechargeName": "quarterly card 20000 USD quota", "billingType": "quarterly", "rmbAmount": 1188, "usdAmount": 20000, "expiresRule": "90 day external shop redeem code package"},
            {"rechargeName": "100 USD permanent quota", "billingType": "permanent", "rmbAmount": 20, "usdAmount": 100, "expiresRule": "External shop redeem code; permanent balance"},
            {"rechargeName": "200 USD permanent quota", "billingType": "permanent", "rmbAmount": 36, "usdAmount": 200, "expiresRule": "External shop redeem code; permanent balance"},
            {"rechargeName": "300 USD permanent quota", "billingType": "permanent", "rmbAmount": 50, "usdAmount": 300, "expiresRule": "External shop redeem code; permanent balance"},
        ],
    },
    "CFUOS364": {
        "stationTypeHint": "mixed",
        "rechargeLocation": "official external pay.ldxp.cn shop redeem code",
        "tierNotes": [
            "zhishu.dev payment config is disabled; recharge evidence uses the official menu-linked pay.ldxp.cn shop verified in the logged-in browser."
        ],
        "products": [
            {"rechargeName": "Codex API 10 USD permanent quota", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10, "expiresRule": "External shop redeem code; product states Codex API 10 USD quota with no expiry"},
            {"rechargeName": "Codex API 20 USD permanent quota", "billingType": "permanent", "rmbAmount": 19, "usdAmount": 20, "expiresRule": "External shop redeem code; product states Codex API 20 USD quota with no expiry"},
            {"rechargeName": "Codex API 50 USD permanent quota", "billingType": "permanent", "rmbAmount": 45, "usdAmount": 50, "expiresRule": "External shop redeem code; product states Codex API 50 USD quota with no expiry"},
            {"rechargeName": "Codex monthly Plus 300 USD quota", "billingType": "monthly", "rmbAmount": 240, "usdAmount": 300, "expiresRule": "30 day external shop package; detail states 20 USD/day, 100 USD/week, 300 USD/month"},
            {"rechargeName": "Codex monthly Pro 500 USD quota", "billingType": "monthly", "rmbAmount": 350, "usdAmount": 500, "expiresRule": "30 day external shop package; detail states 30 USD/day, 150 USD/week, 500 USD/month"},
        ],
    },
    "SAIS2N05": {
        "stationTypeHint": "non_subscription",
        "rechargeLocation": "official external pay.ldxp.cn shop redeem code",
        "tierNotes": [
            "HelloCode payment config is disabled, but the logged-in Recharge/Subscription menu embeds the official pay.ldxp.cn shop with verified Codex redeem-code products."
        ],
        "products": [
            {"rechargeName": "Codex plus/team 10 USD redeem code", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10, "expiresRule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
            {"rechargeName": "Codex plus/team 30 USD redeem code", "billingType": "permanent", "rmbAmount": 30, "usdAmount": 30, "expiresRule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
            {"rechargeName": "Codex plus/team 50 USD redeem code", "billingType": "permanent", "rmbAmount": 50, "usdAmount": 50, "expiresRule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
            {"rechargeName": "Codex plus/team 100 USD redeem code", "billingType": "permanent", "rmbAmount": 100, "usdAmount": 100, "expiresRule": "External shop redeem code; product detail states 1 RMB can redeem 1 USD and code must be redeemed on the station"},
        ],
    },
}


KNOWN_STATION_PAY_SHOPS: dict[str, dict[str, str]] = {
    "lumibest": {
        "token": "WE9ZBUQG",
        "sourceUrl": "https://pay.ldxp.cn/shop/WE9ZBUQG",
    },
    "hello-code": {
        "token": "SAIS2N05",
        "sourceUrl": "https://pay.ldxp.cn/shop/SAIS2N05",
    },
    "zhishu.dev": {
        "token": "CFUOS364",
        "sourceUrl": "https://pay.ldxp.cn/shop/CFUOS364/ek8gty",
    },
}


def known_pay_shop_snapshot(token: str, source_url: str) -> dict[str, Any] | None:
    payload = KNOWN_PAY_SHOP_PRODUCTS.get(token)
    if not payload:
        return None
    tiers: list[dict[str, Any]] = []
    for product in payload.get("products", []):
        row = normalize_recharge_row(
            {
                **product,
                "rechargeLocation": payload.get("rechargeLocation"),
            }
        )
        if row:
            tiers.append(row)
    return {
        "groupMultipliers": [],
        "rechargeTiers": tiers,
        "tierNotes": normalized_tier_notes(payload.get("tierNotes")),
        "sourceUrl": source_url,
        "stationTypeHint": payload.get("stationTypeHint", ""),
    }


def known_station_pay_shop_snapshot(station_key: str) -> dict[str, Any] | None:
    shop = KNOWN_STATION_PAY_SHOPS.get(station_key)
    if not shop:
        return None
    return known_pay_shop_snapshot(shop["token"], shop["sourceUrl"])


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


def decode_escaped_public_html(content: str) -> str:
    text = str(content or "")
    if "\\u003c" not in text.lower() and "\\n" not in text and '\\"' not in text:
        return text
    replacements = {
        "\\u003c": "<",
        "\\u003C": "<",
        "\\u003e": ">",
        "\\u003E": ">",
        "\\u0026": "&",
        "\\u002F": "/",
        "\\/": "/",
        '\\"': '"',
        "\\n": "\n",
        "\\t": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def parse_money_amount(value: Any) -> float | None:
    text = normalize_public_text(html_to_text(value))
    match = re.search(r"(?:[\u00a5\uffe5$]\s*|(?:RMB|CNY|USD)\s*)(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if match:
        return parse_float(match.group(1))
    return parse_float(text)


def parse_duration_days(value: Any) -> float | None:
    text = normalize_public_text(html_to_text(value)).lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\u5c0f\u65f6|hour|hours|hr|hrs)", text, re.IGNORECASE)
    if match:
        hours = parse_float(match.group(1))
        return None if hours is None else hours / 24.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\u5929|\u65e5|day|days)", text, re.IGNORECASE)
    if match:
        return parse_float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\u6708|month|months)", text, re.IGNORECASE)
    if match:
        months = parse_float(match.group(1))
        return None if months is None else months * 30.0
    return None


def public_card_billing_type(duration_days: float | None, title: str) -> str:
    lowered = title.lower()
    if "\u6708\u5361" in title or "month" in lowered:
        return "monthly"
    if "\u5468\u5361" in title or "week" in lowered:
        return "weekly"
    if "\u65e5\u5361" in title or "day" in lowered:
        return "daily"
    if duration_days is not None:
        return billing_type_from_days(round(duration_days))
    return "permanent"


def extract_first_tag_text(content: str, tag: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", content, re.IGNORECASE | re.DOTALL)
    return normalize_public_text(html_to_text(match.group(1))) if match else ""


def public_plan_cards_from_html(content: str) -> list[dict[str, Any]]:
    tiers: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for match in PUBLIC_PLAN_CARD_PATTERN.finditer(content):
        card_html = match.group(1)
        title = extract_first_tag_text(card_html, "h3")
        price_block_match = re.search(
            r"<div\b[^>]*class=[\"'][^\"']*\bffm-price-block\b[^\"']*[\"'][^>]*>(.*?)</div>",
            card_html,
            re.IGNORECASE | re.DOTALL,
        )
        price_block = price_block_match.group(1) if price_block_match else card_html
        strong_values = re.findall(r"<strong\b[^>]*>(.*?)</strong>", price_block, re.IGNORECASE | re.DOTALL)
        price = None
        for value in strong_values:
            price = parse_money_amount(value)
            if price is not None:
                break
        if price is None:
            continue

        dl_values: dict[str, str] = {}
        for item_match in re.finditer(r"<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>", card_html, re.IGNORECASE | re.DOTALL):
            label = normalize_public_text(html_to_text(item_match.group(1)))
            value = normalize_public_text(html_to_text(item_match.group(2)))
            if label and value:
                dl_values[label] = value

        duration_text = " ".join([normalize_public_text(html_to_text(price_block)), *dl_values.values()])
        duration_days = parse_duration_days(duration_text)
        total_quota = None
        daily_quota = None
        for label, value in dl_values.items():
            lowered_label = label.lower()
            if "\u603b\u989d\u5ea6" in label or "total" in lowered_label:
                total_quota = parse_money_amount(value)
            if "\u6bcf\u65e5\u989d\u5ea6" in label or "daily" in lowered_label:
                daily_quota = parse_money_amount(value)

        usd_amount = total_quota
        if usd_amount is None and daily_quota is not None and duration_days is not None:
            usd_amount = daily_quota * max(1.0, duration_days)
        if not title or usd_amount is None:
            continue

        expires_parts: list[str] = []
        if duration_days is not None:
            if duration_days < 1:
                expires_parts.append(f"{format_plain_number(duration_days * 24)} hour package")
            else:
                expires_parts.append(f"{format_plain_number(duration_days)} day package")
        if daily_quota is not None:
            expires_parts.append(f"quota resets daily; daily quota {format_plain_number(daily_quota)} USD")
        elif total_quota is not None:
            expires_parts.append(f"total quota {format_plain_number(total_quota)} USD")
        expires_rule = "; ".join(expires_parts) or "Public marketing package; expiry not stated"
        row = normalize_recharge_row(
            {
                "rechargeName": title,
                "billingType": public_card_billing_type(duration_days, title),
                "rmbAmount": price,
                "usdAmount": usd_amount,
                "rechargeLocation": "public marketing pricing page",
                "expiresRule": expires_rule,
            }
        )
        if not row:
            continue
        key = recharge_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        tiers.append(row)
    return tiers


def minimum_recharge_amount(search_text: str) -> float | None:
    for match in MINIMUM_RECHARGE_PATTERN.finditer(search_text):
        amount = parse_float(match.group(1))
        if amount and amount > 0:
            return amount
    return None


def public_wallet_conversion_rows(search_text: str) -> tuple[list[dict[str, Any]], list[str]]:
    tiers: list[dict[str, Any]] = []
    notes: list[str] = []
    seen_ratios: set[tuple[float, float]] = set()
    for pattern in WALLET_CONVERSION_PATTERNS:
        for match in pattern.finditer(search_text):
            rmb_unit = parse_float(match.group(1))
            usd_unit = parse_float(match.group(2))
            if rmb_unit is None or usd_unit is None or rmb_unit <= 0 or usd_unit <= 0:
                continue
            ratio_key = (rmb_unit, usd_unit)
            if ratio_key in seen_ratios:
                continue
            seen_ratios.add(ratio_key)
            sample_rmb = minimum_recharge_amount(search_text) or rmb_unit
            sample_usd = sample_rmb * usd_unit / rmb_unit
            note = (
                f"Public marketing page conversion sample: {format_plain_number(rmb_unit)} RMB = "
                f"{format_plain_number(usd_unit)} USD credit; not a fixed package; expiry not stated"
            )
            if sample_rmb != rmb_unit:
                note = f"{note}; minimum recharge {format_plain_number(sample_rmb)} RMB"
            row = normalize_recharge_row(
                {
                    "rechargeName": f"wallet topup sample {format_plain_number(sample_rmb)} RMB",
                    "billingType": "permanent",
                    "rmbAmount": sample_rmb,
                    "usdAmount": sample_usd,
                    "rechargeLocation": "public marketing pricing page",
                    "expiresRule": note,
                }
            )
            if row:
                tiers.append(row)
                notes.append(note)
    return tiers, notes


def parse_public_pricing_html(content: str) -> dict[str, Any]:
    recharge_tiers: list[dict[str, Any]] = []
    tier_notes: list[str] = []
    source_url = ""
    station_type_hint = ""
    decoded_content = decode_escaped_public_html(content)
    search_text = normalize_public_text(html_to_text(decoded_content))

    app_config = parse_app_config_from_html(content)
    if app_config:
        station_type_hint = infer_station_type_from_app_config(app_config)
        source_url = sanitize_public_text(app_config.get("api_base_url") or "")
        shop_urls: list[str] = []
        for value in (
            app_config.get("balance_low_notify_recharge_url"),
            app_config.get("purchase_subscription_url"),
        ):
            if isinstance(value, str) and value.strip():
                shop_urls.append(value.strip())
        menu_items = app_config.get("custom_menu_items")
        if isinstance(menu_items, list):
            for item in menu_items:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    shop_urls.append(item["url"])
        for shop_url in shop_urls:
            match = PAY_SHOP_PATTERN.search(shop_url)
            if not match:
                continue
            snapshot = known_pay_shop_snapshot(match.group(1), shop_url)
            if not snapshot:
                continue
            recharge_tiers.extend(snapshot["rechargeTiers"])
            tier_notes.extend(snapshot["tierNotes"])
            if snapshot.get("stationTypeHint") and not station_type_hint:
                station_type_hint = snapshot["stationTypeHint"]
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

    wallet_rows, wallet_notes = public_wallet_conversion_rows(search_text)
    recharge_tiers.extend(wallet_rows)
    tier_notes.extend(wallet_notes)

    recharge_tiers.extend(public_plan_cards_from_html(decoded_content))

    for match in TOPUP_HTML_PATTERN.finditer(decoded_content):
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

    inferred_station_type = infer_station_type_from_recharge_tiers(recharge_tiers)
    if station_type_hint == "mixed":
        pass
    elif inferred_station_type == "mixed":
        station_type_hint = "mixed"
    elif not station_type_hint and inferred_station_type:
        station_type_hint = inferred_station_type

    return {
        "groupMultipliers": [],
        "rechargeTiers": normalized_recharge_rows(recharge_tiers),
        "tierNotes": normalized_tier_notes(tier_notes),
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
                    "rawPayload": {},
                },
            )
            bucket["urls"].extend(collect_public_urls(payload))
            if isinstance(payload.get("results"), dict):
                bucket["rawPayload"] = payload
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
        fallback_label = audit_station_label_from_base_url(summary.get("auditedBaseUrl"), canonical_key)
        row = dict(summary)
        row.update(
            {
                "stationKey": canonical_key,
                "stationLabel": station_display_label(canonical_key, station.get("label") or fallback_label, station.get("url") or summary.get("auditedBaseUrl")),
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
    preserved_station_keys: set[str] | None = None,
) -> None:
    preserved_station_keys = {canonical_station_key(key, station_aliases) for key in (preserved_station_keys or set())}
    for station_key, audit_rows in list(latest_audits.items()):
        if not audit_rows:
            continue

        audited_base_url = sanitize_public_text(audit_rows[0].get("auditedBaseUrl"))
        target_station_key = station_key
        if station_key not in stations and station_key not in preserved_station_keys:
            matching_station_key = find_station_key_by_url_host(stations, station_urls, audited_base_url)
            if matching_station_key:
                target_station_key = matching_station_key
                existing_audits = latest_audits.setdefault(target_station_key, [])
                seen_audits = {
                    (row.get("model"), row.get("executedAt"), row.get("reportPath"))
                    for row in existing_audits
                }
                for row in audit_rows:
                    marker = (row.get("model"), row.get("executedAt"), row.get("reportPath"))
                    if marker not in seen_audits:
                        existing_audits.append(row)
                        seen_audits.add(marker)
                existing_audits.sort(key=lambda item: audit_sort_datetime(item.get("executedAt")), reverse=True)
                latest_audits.pop(station_key, None)

        if target_station_key in stations:
            station = ensure_station(stations, target_station_key, station_aliases=station_aliases)
            if audited_base_url and not station.get("url"):
                station["url"] = audited_base_url
        else:
            station = ensure_station(
                stations,
                target_station_key,
                station_aliases=station_aliases,
                label=station_display_label(
                    target_station_key,
                    audit_station_label_from_base_url(audited_base_url, target_station_key),
                    audited_base_url,
                ),
                url=audited_base_url,
            )

        if audited_base_url:
            add_exact_station_url(station_urls, target_station_key, audited_base_url, station_aliases)


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


def load_station_url_overrides(station_aliases: dict[str, str] | None = None) -> dict[str, str]:
    if not STATION_URL_OVERRIDES_PATH.exists():
        return {}
    payload = json.loads(STATION_URL_OVERRIDES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    overrides: dict[str, str] = {}
    for station_key, value in payload.items():
        canonical_key = canonical_station_key(station_key, station_aliases)
        override_url = sanitize_public_text(value)
        if canonical_key and is_public_station_url(override_url):
            overrides[canonical_key] = override_url
    return overrides


def load_station_invite_links(station_aliases: dict[str, str] | None = None) -> dict[str, str]:
    if not STATION_INVITE_LINKS_PATH.exists():
        return {}
    payload = json.loads(STATION_INVITE_LINKS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    invite_links: dict[str, str] = {}
    for station_key, value in payload.items():
        canonical_key = canonical_station_key(station_key, station_aliases)
        invite_url = sanitize_public_text(value)
        if canonical_key and is_public_station_url(invite_url):
            invite_links[canonical_key] = invite_url
    return invite_links


def formal_ranked_station_keys(rankings: dict[str, list[dict[str, Any]]]) -> set[str]:
    return {
        str(row.get("station") or "").strip()
        for rows in rankings.values()
        for row in rows
        if str(row.get("station") or "").strip()
    }


def apply_invite_links_to_rankings(
    rankings: dict[str, list[dict[str, Any]]],
    invite_links: dict[str, str],
) -> dict[str, Any]:
    ranked_keys = formal_ranked_station_keys(rankings)
    applied: list[dict[str, str]] = []
    fallback: list[dict[str, str]] = []

    for rows in rankings.values():
        for row in rows:
            station_key = str(row.get("station") or "").strip()
            if not station_key:
                continue
            invite_url = invite_links.get(station_key, "")
            if invite_url:
                original_url = sanitize_public_text(row.get("stationUrl"))
                row["stationUrl"] = invite_url
                applied.append(
                    {
                        "station": station_key,
                        "timeWindow": str(row.get("timeWindow") or ""),
                        "originalUrl": original_url,
                        "inviteUrl": invite_url,
                    }
                )

    for station_key in sorted(ranked_keys):
        if station_key not in invite_links:
            fallback.append({"station": station_key, "status": "fallback_official_url"})

    configured_not_ranked = sorted(key for key in invite_links if key not in ranked_keys)
    return {
        "rankedStationCount": len(ranked_keys),
        "configuredInviteCount": len(invite_links),
        "appliedRowCount": len(applied),
        "fallbackOfficialUrlCount": len(fallback),
        "fallbackOfficialUrl": fallback,
        "configuredNotRanked": configured_not_ranked,
    }


def apply_invite_links_to_stations(
    stations: dict[str, dict[str, Any]],
    invite_links: dict[str, str],
) -> None:
    for station_key, station in stations.items():
        invite_url = invite_links.get(station_key, "")
        if invite_url:
            station["inviteUrl"] = invite_url
        else:
            station.pop("inviteUrl", None)


def detach_station_ranking_rows(stations: dict[str, dict[str, Any]]) -> None:
    for station in stations.values():
        rankings = station.get("rankings")
        if not isinstance(rankings, dict):
            continue
        station["rankings"] = {
            window_key: deepcopy(row)
            for window_key, row in rankings.items()
            if isinstance(row, dict)
        }


def write_invite_link_report(report: dict[str, Any]) -> None:
    INVITE_LINK_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVITE_LINK_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


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
        if normalized_group_rows(snapshot.get("groupMultipliers")):
            station["groupMultipliers"] = []
        if normalized_recharge_rows(snapshot.get("rechargeTiers")):
            station["rechargeTiers"] = []
        for group in snapshot.get("groupMultipliers", []):
            append_group_row(station, group)
        for tier in snapshot.get("rechargeTiers", []):
            append_recharge_row(station, tier)
        merge_tier_notes(station, snapshot.get("tierNotes", []))


def apply_live_probe_snapshots(
    stations: dict[str, dict[str, Any]],
    station_urls: dict[str, set[str]],
    live_snapshots: dict[str, dict[str, Any]],
    *,
    station_aliases: dict[str, str] | None = None,
) -> None:
    for station_key, snapshot in live_snapshots.items():
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
        if normalized_group_rows(snapshot.get("groupMultipliers")):
            station["groupMultipliers"] = []
        if normalized_recharge_rows(snapshot.get("rechargeTiers")):
            station["rechargeTiers"] = []
            station["verifiedTierCount"] = max(
                parse_int(station.get("verifiedTierCount")),
                parse_int(snapshot.get("verifiedTierCount")),
            )
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
            "source": public_source_text((live_status or {}).get("source")),
        }

    status = sanitize_public_text((live_status or {}).get("status")) or fallback_status
    message = normalize_public_text((live_status or {}).get("message")) or fallback_message
    source = public_source_text((live_status or {}).get("source"))
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
    group_count = len(station.get("groupMultipliers", []))
    recharge_count = len(station.get("rechargeTiers", []))
    announcement_count = len(station.get("announcements", []))
    public_probe_snapshot = station.get("_publicProbeSnapshot") if isinstance(station.get("_publicProbeSnapshot"), dict) else None
    root_unavailable_status = public_probe_root_status(public_probe_snapshot)
    announcement_live_status = (
        live_statuses.get("announcements")
        if isinstance(live_statuses.get("announcements"), dict)
        else None
    )
    login_block_status = None
    if isinstance(live_snapshot, dict):
        login_block_status = probe_login_block_status(
            live_snapshot.get("rawProbe"),
            message="登录态接口被验证码或风控阻断",
        )
    sub2api_login_message = "sub2api 的该类接口通常需要登录态；当前公开快照或已归档 probe 没有可用结构化数据。"
    announcement_message = (
        "sub2api 公告通常位于登录态 /api/v1/announcements；当前没有抓到可展示内容。"
        if platform == "sub2api"
        else "未发现标准公开公告接口或接口未返回公告内容。"
    )
    group_live_status = live_statuses.get("groupMultipliers") if isinstance(live_statuses.get("groupMultipliers"), dict) else None
    recharge_live_status = live_statuses.get("rechargeTiers") if isinstance(live_statuses.get("rechargeTiers"), dict) else None
    if root_unavailable_status and (group_live_status or {}).get("status") == "login_required":
        group_live_status = root_unavailable_status
    if root_unavailable_status and (recharge_live_status or {}).get("status") == "login_required":
        recharge_live_status = root_unavailable_status
    weak_statuses = {"login_required", "failed", "missing", "public_missing", ""}
    if login_block_status and group_count == 0 and (
        group_live_status is None
        or (group_live_status or {}).get("status") in weak_statuses
    ):
        group_live_status = login_block_status
    if login_block_status and recharge_count == 0 and (
        recharge_live_status is None
        or (recharge_live_status or {}).get("status") in weak_statuses
    ):
        recharge_live_status = login_block_status
    if login_block_status and announcement_count == 0 and (
        announcement_live_status is None
        or (announcement_live_status or {}).get("status") in weak_statuses
    ):
        announcement_live_status = login_block_status
    if root_unavailable_status and (
        announcement_live_status is None
        or (announcement_live_status or {}).get("status") in {"login_required", "failed", "public_missing", ""}
    ):
        announcement_live_status = root_unavailable_status
    evidence_rows = [
        evidence_item(
            key="groupMultipliers",
            label="分组倍率",
            count=group_count,
            fallback_status="login_required" if platform == "sub2api" else "missing",
            fallback_message=root_unavailable_status["message"] if root_unavailable_status else (sub2api_login_message if platform == "sub2api" else "当前未抓到结构化分组倍率。"),
            live_status=group_live_status or root_unavailable_status,
        ),
        evidence_item(
            key="rechargeTiers",
            label="充值档位",
            count=recharge_count,
            fallback_status="login_required" if platform == "sub2api" else "missing",
            fallback_message=root_unavailable_status["message"] if root_unavailable_status else (sub2api_login_message if platform == "sub2api" else "当前未抓到结构化充值档位。"),
            live_status=recharge_live_status or root_unavailable_status,
        ),
        evidence_item(
            key="announcements",
            label="公告",
            count=announcement_count,
            fallback_status="login_required" if platform == "sub2api" else "public_missing",
            fallback_message=root_unavailable_status["message"] if root_unavailable_status else announcement_message,
            live_status=announcement_live_status or root_unavailable_status,
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
        station_type_hint = sanitize_public_text(override.get("stationTypeHint") or override.get("station_type"))
        if station_type_hint in FULL_TYPE_LABELS and station_type_hint != "unknown_pending":
            station["stationType"] = station_type_hint
            station["stationTypeLabel"] = FULL_TYPE_LABELS.get(station_type_hint, station_type_hint)
            station["stationTypeShortLabel"] = SHORT_TYPE_LABELS.get(station_type_hint, station_type_hint)

        group_rows = []
        for item in override.get("groupMultipliers", []):
            if isinstance(item, dict):
                normalized = normalize_group_row(item)
                if normalized:
                    group_rows.append(normalized)
        if group_rows:
            station["groupMultipliers"] = group_rows

        explicit_recharge_rows = []
        for item in override.get("rechargeTiers", []):
            if isinstance(item, dict):
                normalized = normalize_recharge_row(item)
                if normalized:
                    explicit_recharge_rows.append(normalized)
        if explicit_recharge_rows:
            station["rechargeTiers"] = sort_recharge_tiers(explicit_recharge_rows)
            station["verifiedTierCount"] = max(parse_int(station.get("verifiedTierCount")), len(explicit_recharge_rows))

        recharge_mode = override.get("rechargeMode")
        if explicit_recharge_rows:
            pass
        elif recharge_mode == "linear_rmb_to_usd":
            usd_per_rmb = parse_float(override.get("usdPerRmb")) or 0.0
            recharge_pattern = re.compile(str(override.get("rechargeNamePattern") or TOPUP_NAME_PATTERN.pattern), re.IGNORECASE)
            updated_tiers: list[dict[str, Any]] = []
            for tier in station.get("rechargeTiers", []):
                next_tier = deepcopy(tier)
                if recharge_pattern.search(next_tier.get("rechargeName", "")) and next_tier.get("rmbAmount") is not None and usd_per_rmb > 0:
                    next_tier["usdAmount"] = round(float(next_tier["rmbAmount"]) * usd_per_rmb, 10)
                updated_tiers.append(next_tier)
            station["rechargeTiers"] = sort_recharge_tiers(updated_tiers)
        elif recharge_mode == "sample_amount_to_usd_with_response_rmb":
            usd_per_sample_unit = parse_float(override.get("usdPerSampleUnit")) or 0.0
            recharge_pattern = re.compile(str(override.get("rechargeNamePattern") or TOPUP_NAME_PATTERN.pattern), re.IGNORECASE)
            name_template = str(override.get("rechargeNameTemplate") or "wallet topup sample {rmb} RMB")
            updated_tiers = []
            for tier in station.get("rechargeTiers", []):
                next_tier = deepcopy(tier)
                match = recharge_pattern.search(next_tier.get("rechargeName", ""))
                sample_amount = parse_float(match.group(1)) if match else parse_float(next_tier.get("rmbAmount"))
                actual_rmb = parse_float(next_tier.get("usdAmount"))
                if match and sample_amount is not None and actual_rmb is not None and usd_per_sample_unit > 0:
                    next_tier["rmbAmount"] = round(actual_rmb, 10)
                    next_tier["usdAmount"] = round(sample_amount * usd_per_sample_unit, 10)
                    next_tier["rechargeName"] = name_template.format(rmb=format_plain_number(actual_rmb))
                updated_tiers.append(next_tier)
            station["rechargeTiers"] = sort_recharge_tiers(updated_tiers)
        elif recharge_mode == "sample_payment_amount_to_usd_1to1":
            usd_per_payment_unit = parse_float(override.get("usdPerPaymentUnit")) or 1.0
            sample_payment_amount = parse_float(override.get("samplePaymentAmount"))
            recharge_pattern = re.compile(str(override.get("rechargeNamePattern") or TOPUP_NAME_PATTERN.pattern), re.IGNORECASE)
            name_template = str(override.get("rechargeNameTemplate") or "wallet topup sample {rmb} RMB")
            recharge_location = sanitize_public_text(override.get("rechargeLocation"))
            expires_rule = sanitize_public_text(override.get("expiresRule"))
            updated_tiers = []
            seen_tiers: set[tuple[str | None, float | None, float | None]] = set()
            for tier in station.get("rechargeTiers", []):
                next_tier = deepcopy(tier)
                match = recharge_pattern.search(next_tier.get("rechargeName", ""))
                payment_amount = sample_payment_amount
                if payment_amount is None and match:
                    payment_amount = parse_float(match.group(1))
                if payment_amount is None:
                    payment_amount = parse_float(next_tier.get("usdAmount")) or parse_float(next_tier.get("rmbAmount"))
                if (match or sample_payment_amount is not None) and payment_amount is not None and payment_amount > 0 and usd_per_payment_unit > 0:
                    usd_amount = payment_amount * usd_per_payment_unit
                    next_tier["rmbAmount"] = round(payment_amount, 10)
                    next_tier["usdAmount"] = round(usd_amount, 10)
                    next_tier["rechargeName"] = name_template.format(
                        rmb=format_plain_number(payment_amount),
                        usd=format_plain_number(usd_amount),
                    )
                    if recharge_location:
                        next_tier["rechargeLocation"] = recharge_location
                    if expires_rule:
                        next_tier["expiresRule"] = expires_rule
                key = (
                    next_tier.get("rechargeName"),
                    parse_float(next_tier.get("rmbAmount")),
                    parse_float(next_tier.get("usdAmount")),
                )
                if key in seen_tiers:
                    continue
                seen_tiers.add(key)
                updated_tiers.append(next_tier)
            station["rechargeTiers"] = sort_recharge_tiers(updated_tiers)

        assumption_text = sanitize_public_text(override.get("assumptionText"))
        drop_note_patterns = [
            re.compile(str(pattern), re.IGNORECASE)
            for pattern in override.get("dropTierNotePatterns", [])
            if str(pattern or "").strip()
        ]
        if drop_note_patterns:
            station["tierNotes"] = [
                note
                for note in station.get("tierNotes", [])
                if not any(pattern.search(str(note)) for pattern in drop_note_patterns)
            ]
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
            0 if parse_int(row.get("requests")) >= PRIORITY_RANKING_MIN_REQUESTS else 1,
            -float(row.get("totalScore", 0.0)),
            -parse_int(row.get("requests")),
            str(row.get("station") or ""),
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
    ensure_runtime_dirs()
    station_aliases = load_station_aliases()
    existing_detail_baseline = load_existing_detail_baseline(station_aliases)
    existing_station_records = load_existing_station_records(station_aliases)
    postgres_base_stations = load_postgres_base_site_snapshot(station_aliases)

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
        tier_rows = read_csv(resolved_inputs["multiplier_tiers.csv"])
        tier_groups = multiplier_tier_row_groups(tier_rows, station_aliases=station_aliases)
        for station_key, payload in tier_groups.items():
            station = stations.get(station_key)
            if not station:
                continue
            station["verifiedTierCount"] = 0
            if payload.get("groupMultipliers"):
                station["groupMultipliers"] = []
            if payload.get("rechargeTiers"):
                station["rechargeTiers"] = []
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

    apply_existing_detail_baseline(stations, station_urls, existing_detail_baseline, station_aliases=station_aliases)

    status_payloads = load_status_payloads(station_aliases)
    announcements = load_announcements(status_payloads)
    for station_key, payload in status_payloads.items():
        if not is_public_station_key(station_key):
            continue
        if station_key not in stations:
            continue
        data = payload.get("data") if isinstance(payload, dict) else {}
        if isinstance(data, dict):
            source_url = sanitize_public_text(data.get("server_address"))
            if source_url:
                add_station_url(station_urls, station_key, source_url, station_aliases)

    pricing_snapshots = {
        station_key: snapshot
        for station_key, snapshot in load_public_pricing_snapshots(station_aliases).items()
        if station_key in stations
    }
    apply_public_pricing_snapshots(stations, station_urls, pricing_snapshots, station_aliases=station_aliases)

    public_probes = {
        station_key: snapshot
        for station_key, snapshot in load_public_probe_snapshots(station_aliases).items()
        if station_key in stations
    }
    for station_key, snapshot in public_probes.items():
        for url in snapshot.get("urls", []):
            add_station_url(station_urls, station_key, url, station_aliases)
        if station_key in stations:
            stations[station_key]["_publicProbeCaptured"] = True
            if isinstance(snapshot.get("rawPayload"), dict):
                stations[station_key]["_publicProbeSnapshot"] = snapshot["rawPayload"]
            if snapshot.get("evidenceStatus", {}).get("publicProbe"):
                stations[station_key].setdefault("_publicEvidenceStatus", {})
                stations[station_key]["_publicEvidenceStatus"]["publicProbe"] = snapshot["evidenceStatus"]["publicProbe"]

    for station_key, rows in announcements.items():
        if not is_public_station_key(station_key):
            continue
        if station_key not in stations:
            continue
        station = ensure_station(stations, station_key, station_aliases=station_aliases)
        station["announcements"] = merge_announcements(station.get("announcements", []), rows)

    live_snapshots = {
        station_key: snapshot
        for station_key, snapshot in load_live_probe_snapshots(station_aliases).items()
        if station_key in stations
    }
    apply_live_probe_snapshots(stations, station_urls, live_snapshots, station_aliases=station_aliases)

    overrides = load_station_pricing_overrides(station_aliases)
    url_overrides = load_station_url_overrides(station_aliases)
    invite_links = load_station_invite_links(station_aliases)
    apply_station_pricing_overrides(stations, overrides, station_aliases=station_aliases)

    audit_targets = load_station_audit_targets(station_aliases)
    latest_audits = load_latest_station_audits(station_aliases)
    preserved_audit_station_keys = set(existing_station_records) | set(postgres_base_stations)
    apply_audit_only_station_records(
        stations,
        station_urls,
        latest_audits,
        station_aliases=station_aliases,
        preserved_station_keys=preserved_audit_station_keys,
    )
    apply_existing_detail_baseline(stations, station_urls, existing_detail_baseline, station_aliases=station_aliases)
    apply_postgres_base_station_records(
        stations,
        station_urls,
        existing_station_records,
        station_aliases=station_aliases,
        preserved_station_keys=set(existing_station_records),
    )
    apply_postgres_base_station_records(
        stations,
        station_urls,
        postgres_base_stations,
        station_aliases=station_aliases,
        preserved_station_keys=set(postgres_base_stations),
    )
    dedupe_station_tier_notes(stations)

    apply_authoritative_ranking_overrides(stations, rankings, overrides)

    for station in stations.values():
        url_choices = dedupe_strings(list(station_urls.get(station["key"], set())) + [station.get("url", "")])
        station["url"] = choose_display_url(
            station["key"],
            url_choices,
            url_overrides,
            current_url=station.get("url", ""),
        )
        station["label"] = station_display_label(station["key"], station.get("label"), station.get("url"))

    apply_invite_links_to_stations(stations, invite_links)

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
        station.pop("_publicProbeSnapshot", None)

    sync_station_metadata_into_rows(stations, rankings)
    detach_station_ranking_rows(stations)
    invite_link_report = apply_invite_links_to_rankings(rankings, invite_links)
    write_invite_link_report(invite_link_report)

    site_data = {
        "siteName": "AI中转站监视者",
        "projectName": "api-relay-rank",
        "generatedAt": intro["generated_at"],
        "timezone": "Asia/Shanghai",
        "defaultTimeWindow": "all_hours",
        "defaultSort": "composite",
        "declaration": intro["declaration"],
        "timeWindows": TIME_WINDOWS,
        "rankings": rankings,
        "stations": station_list,
        "rankedStationCount": {window: len(rows) for window, rows in rankings.items()},
    }

    SITE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA_PATH.write_text(json.dumps(site_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "generated_at": intro["generated_at"],
                "output": logical_data_path(SITE_DATA_PATH),
                "stations": len(station_list),
                "work_hours_ranked": len(rankings["work_hours"]),
                "off_hours_ranked": len(rankings["off_hours"]),
                "reused_existing": use_existing_base,
                "missing_sources": missing_inputs,
                "invite_link_report": logical_data_path(INVITE_LINK_REPORT_PATH),
                "invite_link_fallback_official_url": invite_link_report["fallbackOfficialUrlCount"],
                "data_gaps": data_gap_summary(station_list),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
