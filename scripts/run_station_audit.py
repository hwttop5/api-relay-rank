#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

try:
    from scripts.runtime_paths import (
        APP_ROOT,
        AUDIT_RUNS_DIR,
        DATA_DIR,
        ensure_runtime_dirs,
        exclusive_lock,
        logical_data_path,
    )
except ModuleNotFoundError:
    from runtime_paths import (
        APP_ROOT,
        AUDIT_RUNS_DIR,
        DATA_DIR,
        ensure_runtime_dirs,
        exclusive_lock,
        logical_data_path,
    )

CONFIG_PATH = APP_ROOT / "config" / "station_audit_targets.json"
ENGINE_PATH = APP_ROOT / "vendor" / "api_relay_audit" / "audit.py"
ENGINE_COMMIT = "408e3f0b0ce25ae4cbe74add121c2fe30dc66583"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_LATENCY_PROBE_COUNT = 10
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 3600
MIN_WARMUP = 0
MAX_WARMUP = 20
MIN_LATENCY_PROBE_COUNT = 3
MAX_LATENCY_PROBE_COUNT = 50
AUDIT_PROFILE = "general"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_RETENTION_MAX_PER_TARGET = 20
OPENAI_AUDIT_FAMILY = "openai"
ANTHROPIC_AUDIT_FAMILY = "anthropic"
GEMINI_AUDIT_FAMILY = "gemini"
UNKNOWN_AUDIT_FAMILY = "unknown"
LEGACY_CLAUDE_FALSE_POSITIVE_RE = re.compile(
    r"(?:^|;\s*)Stream's message_start\.message\.model = '[^']+' does not contain 'claude'\s*[-\u2013\u2014\u2015\u2026\uFF0D\uFE58\uFE63\uFF0D\uFFFD?]*\s*relay may be routing to a substitute model",
    flags=re.IGNORECASE,
)

OPTION_BOOL_FIELDS = {
    "skipInfra",
    "skipContext",
    "skipToolSubstitution",
    "skipErrorLeakage",
    "skipStreamIntegrity",
    "skipInfraFingerprint",
    "skipLatencyVariance",
    "aggressiveErrorProbes",
}


class AuditConfigError(RuntimeError):
    """Raised when station audit configuration is invalid."""


@dataclass(frozen=True)
class AuditRunOptions:
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    warmup: int = 0
    latency_probe_count: int = DEFAULT_LATENCY_PROBE_COUNT
    skip_infra: bool = False
    skip_context: bool = False
    skip_tool_substitution: bool = False
    skip_error_leakage: bool = False
    skip_stream_integrity: bool = False
    skip_infra_fingerprint: bool = False
    skip_latency_variance: bool = False
    aggressive_error_probes: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "timeout": self.timeout,
            "warmup": self.warmup,
            "latencyProbeCount": self.latency_probe_count,
            "skipInfra": self.skip_infra,
            "skipContext": self.skip_context,
            "skipToolSubstitution": self.skip_tool_substitution,
            "skipErrorLeakage": self.skip_error_leakage,
            "skipStreamIntegrity": self.skip_stream_integrity,
            "skipInfraFingerprint": self.skip_infra_fingerprint,
            "skipLatencyVariance": self.skip_latency_variance,
            "aggressiveErrorProbes": self.aggressive_error_probes,
        }


@dataclass
class StationAuditSummary:
    profile: str
    model: str
    audited_base_url: str
    executed_at: str
    overall_verdict: str
    overall_summary: str
    highlights: list[str]
    step_summaries: list[dict[str, str]]
    report_path: str
    tool_version: str
    duration_ms: int
    effective_options: dict[str, Any]
    audit_score: int
    audit_verdict_reason: str
    capability_verdict: str
    protocol_verdict: str
    authenticity_verdict: str
    long_context_verdict: str
    detector_results: list[dict[str, Any]]
    critical_findings: list[str]
    run_mode: str
    cost_notice: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "model": self.model,
            "auditedBaseUrl": self.audited_base_url,
            "executedAt": self.executed_at,
            "overallVerdict": self.overall_verdict,
            "overallSummary": self.overall_summary,
            "highlights": self.highlights,
            "stepSummaries": self.step_summaries,
            "reportPath": self.report_path,
            "toolVersion": self.tool_version,
            "runStatus": "success",
            "durationMs": self.duration_ms,
            "engineCommit": ENGINE_COMMIT,
            "effectiveOptions": self.effective_options,
            "auditScore": self.audit_score,
            "auditVerdictReason": self.audit_verdict_reason,
            "capabilityVerdict": self.capability_verdict,
            "protocolVerdict": self.protocol_verdict,
            "authenticityVerdict": self.authenticity_verdict,
            "longContextVerdict": self.long_context_verdict,
            "detectorResults": self.detector_results,
            "criticalFindings": self.critical_findings,
            "runMode": self.run_mode,
            "costNotice": self.cost_notice,
        }


def slugify_model(model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model.strip()).strip("-")
    return slug or "model"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_run_dir_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def validate_absolute_url(value: str, *, station: str, field: str) -> str:
    text = value.strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AuditConfigError(f"Audit target '{station}' field '{field}' must be an absolute HTTP(S) URL.")
    return text


def require_bool(item: dict[str, Any], field: str, *, station: str) -> bool:
    if field not in item:
        return False
    if not isinstance(item[field], bool):
        raise AuditConfigError(f"Audit target '{station}' field '{field}' must be a boolean.")
    return item[field]


def int_option(item: dict[str, Any], field: str, *, station: str, default: int, minimum: int, maximum: int) -> int:
    if field not in item:
        return default
    value = item[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuditConfigError(f"Audit target '{station}' field '{field}' must be an integer.")
    if value < minimum or value > maximum:
        raise AuditConfigError(f"Audit target '{station}' field '{field}' must be between {minimum} and {maximum}.")
    return value


def validate_models(value: Any, *, station: str) -> list[str]:
    if not isinstance(value, list):
        raise AuditConfigError(f"Audit target '{station}' must define a non-empty 'models' list.")
    models = [str(model).strip() for model in value]
    if not models or any(not model for model in models):
        raise AuditConfigError(f"Audit target '{station}' must define a non-empty 'models' list.")
    if len(models) != len(set(models)):
        raise AuditConfigError(f"Audit target '{station}' has duplicate models.")
    return models


def options_from_mapping(item: dict[str, Any], *, station: str, timeout_override: int | None = None) -> AuditRunOptions:
    timeout = timeout_override if timeout_override is not None else int_option(
        item,
        "timeout",
        station=station,
        default=DEFAULT_TIMEOUT_SECONDS,
        minimum=MIN_TIMEOUT_SECONDS,
        maximum=MAX_TIMEOUT_SECONDS,
    )
    if timeout < MIN_TIMEOUT_SECONDS or timeout > MAX_TIMEOUT_SECONDS:
        raise AuditConfigError(f"Audit target '{station}' field 'timeout' must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}.")

    return AuditRunOptions(
        timeout=timeout,
        warmup=int_option(item, "warmup", station=station, default=0, minimum=MIN_WARMUP, maximum=MAX_WARMUP),
        latency_probe_count=int_option(
            item,
            "latencyProbeCount",
            station=station,
            default=DEFAULT_LATENCY_PROBE_COUNT,
            minimum=MIN_LATENCY_PROBE_COUNT,
            maximum=MAX_LATENCY_PROBE_COUNT,
        ),
        skip_infra=require_bool(item, "skipInfra", station=station),
        skip_context=require_bool(item, "skipContext", station=station),
        skip_tool_substitution=require_bool(item, "skipToolSubstitution", station=station),
        skip_error_leakage=require_bool(item, "skipErrorLeakage", station=station),
        skip_stream_integrity=require_bool(item, "skipStreamIntegrity", station=station),
        skip_infra_fingerprint=require_bool(item, "skipInfraFingerprint", station=station),
        skip_latency_variance=require_bool(item, "skipLatencyVariance", station=station),
        aggressive_error_probes=require_bool(item, "aggressiveErrorProbes", station=station),
    )


def merge_option_overrides(base: AuditRunOptions, args: argparse.Namespace) -> AuditRunOptions:
    payload = base.to_payload()
    if args.timeout is not None:
        payload["timeout"] = args.timeout
    if args.warmup is not None:
        payload["warmup"] = args.warmup
    if args.latency_probe_count is not None:
        payload["latencyProbeCount"] = args.latency_probe_count
    for attr, field in [
        ("skip_infra", "skipInfra"),
        ("skip_context", "skipContext"),
        ("skip_tool_substitution", "skipToolSubstitution"),
        ("skip_error_leakage", "skipErrorLeakage"),
        ("skip_stream_integrity", "skipStreamIntegrity"),
        ("skip_infra_fingerprint", "skipInfraFingerprint"),
        ("skip_latency_variance", "skipLatencyVariance"),
        ("aggressive_error_probes", "aggressiveErrorProbes"),
    ]:
        if getattr(args, attr, False):
            payload[field] = True
    return options_from_mapping(payload, station=args.station, timeout_override=payload["timeout"])


def load_targets() -> list[dict[str, Any]]:
    if not CONFIG_PATH.exists():
        raise AuditConfigError(f"Missing audit config: {CONFIG_PATH}")
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    targets = payload.get("targets") if isinstance(payload, dict) else None
    if not isinstance(targets, list):
        raise AuditConfigError("Audit config must contain a top-level 'targets' array.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(targets, start=1):
        if not isinstance(item, dict):
            raise AuditConfigError(f"Audit target #{index} must be an object.")
        station = str(item.get("station") or "").strip()
        if not station:
            raise AuditConfigError(f"Audit target #{index} is missing 'station'.")
        profile = str(item.get("profile") or AUDIT_PROFILE).strip() or AUDIT_PROFILE
        if profile != AUDIT_PROFILE:
            raise AuditConfigError(f"Audit target '{station}' uses unsupported profile '{profile}'. Only 'general' is supported.")
        models = validate_models(item.get("models"), station=station)
        default_model = str(item.get("defaultModel") or "").strip()
        if default_model and default_model not in set(models):
            raise AuditConfigError(f"Audit target '{station}' has defaultModel not present in models.")
        api_key_env = str(item.get("apiKeyEnv") or "").strip()
        if not api_key_env:
            raise AuditConfigError(f"Audit target '{station}' is missing 'apiKeyEnv'.")
        audit_base_url = validate_absolute_url(str(item.get("auditBaseUrl") or ""), station=station, field="auditBaseUrl")
        options = options_from_mapping(item, station=station)
        normalized.append(
            {
                "station": station,
                "auditBaseUrl": audit_base_url,
                "profile": AUDIT_PROFILE,
                "models": models,
                "defaultModel": default_model or models[0],
                "apiKeyEnv": api_key_env,
                "enabled": bool(item.get("enabled")),
                "options": options,
            }
        )
    return normalized


def get_target(station: str, *, include_disabled: bool) -> dict[str, Any]:
    for target in load_targets():
        if target["station"] != station:
            continue
        if target["enabled"] or include_disabled:
            return target
        raise AuditConfigError(f"Audit target '{station}' is disabled.")
    raise AuditConfigError(f"Unknown audit target: {station}")


def markdown_to_plain(text: str) -> str:
    normalized = re.sub(r"`([^`]+)`", r"\1", text)
    normalized = re.sub(r"\*\*([^*]+)\*\*", r"\1", normalized)
    normalized = re.sub(r"\*([^*]+)\*", r"\1", normalized)
    normalized = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 \2", normalized)
    normalized = re.sub(r"^#{1,6}\s*", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def sanitize_text(value: Any, secrets: list[str] | None = None) -> str:
    text = str(value or "")
    for secret in secrets or []:
        if secret:
            text = text.replace(secret, "<redacted>")
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]{8,}", r"\1<redacted>", text)
    text = re.sub(r"\bsk-[A-Za-z0-9._\-]{6,}\b", "sk-<redacted>", text)
    text = re.sub(r"([A-Za-z]:\\Users\\)([^\\\r\n`\"']+)", r"\1xxx", text)
    text = re.sub(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b", "xxx", text)
    text = re.sub(r"(?i)ttop5", "xxx", text)
    return text


def sanitized_command(command: list[str], secrets: list[str]) -> list[str]:
    output: list[str] = []
    redact_next = False
    for part in command:
        if redact_next:
            output.append("<redacted>")
            redact_next = False
            continue
        output.append(sanitize_text(part, secrets))
        if part == "--key":
            redact_next = True
    return output


def strip_heading_number(title: str) -> str:
    return re.sub(r"^\d+\.\s*", "", title.strip()).strip()


def audit_model_family(model: str) -> str:
    value = str(model or "").strip().lower()
    if not value:
        return UNKNOWN_AUDIT_FAMILY
    normalized = value.removeprefix("models/")
    if normalized.startswith("claude-") or normalized == "claude":
        return ANTHROPIC_AUDIT_FAMILY
    if (
        normalized.startswith("gpt-")
        or normalized.startswith("chatgpt-")
        or re.match(r"^o[1345](?:-|$)", normalized)
        or normalized.startswith("codex-")
        or normalized.startswith("computer-use-")
        or normalized.startswith("text-")
        or normalized.startswith("davinci")
        or normalized.startswith("babbage")
    ):
        return OPENAI_AUDIT_FAMILY
    if normalized.startswith("gemini-"):
        return GEMINI_AUDIT_FAMILY
    return UNKNOWN_AUDIT_FAMILY


def remove_legacy_claude_stream_false_positive(text: str, model: str) -> str:
    if audit_model_family(model) != OPENAI_AUDIT_FAMILY or not text:
        return text
    cleaned = text.replace("non-Claude stream model name", "unexpected stream model family/name")
    if "does not contain 'claude'" not in cleaned.lower():
        return cleaned.strip()
    cleaned = LEGACY_CLAUDE_FALSE_POSITIVE_RE.sub("", cleaned)
    cleaned = re.sub(r"\s*;\s*([.;])", r"\1", cleaned)
    cleaned = re.sub(r":\s*;", ":", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def legacy_line_has_real_stream_anomaly(line: str) -> bool:
    lowered = line.lower()
    return any(
        marker in lowered
        for marker in [
            "input_tokens",
            "output_tokens",
            "usage rewrite",
            "unknown sse",
            "non-monotonic",
            "signature_delta",
            "empty signature",
        ]
    )


def clean_legacy_audit_report_for_model(report_text: str, model: str) -> str:
    if audit_model_family(model) != OPENAI_AUDIT_FAMILY:
        return report_text
    cleaned_lines: list[str] = []
    for raw_line in report_text.splitlines():
        line = remove_legacy_claude_stream_false_positive(raw_line, model)
        lowered = line.lower()
        if raw_line.lower().strip().startswith("- stream's message_start.message.model") and "does not contain 'claude'" in raw_line.lower():
            continue
        if (
            "stream integrity anomaly detected" in lowered
            and "does not contain 'claude'" in raw_line.lower()
            and not legacy_line_has_real_stream_anomaly(line)
        ):
            continue
        line = re.sub(r"\(NOT claude\)", "(matches OpenAI/GPT)", line, flags=re.IGNORECASE)
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def report_sections(report_text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^##\s+([^\n]+?)\s*$", report_text, flags=re.MULTILINE))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(report_text)
        sections.append((match.group(1).strip(), report_text[body_start:body_end]))
    return sections


def parse_overall_verdict(report_text: str) -> tuple[str, str]:
    verdict_map = {
        "high": "high",
        "medium": "medium",
        "low": "low",
    }
    section_body = ""
    for title, body in report_sections(report_text):
        if strip_heading_number(title).lower() == "overall rating":
            section_body = body
            break
    search_space = section_body or report_text
    match = re.search(r"^###\s*(HIGH|MEDIUM|LOW)\s+RISK\s*$", search_space, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return "inconclusive", "Audit report did not contain a supported overall verdict section."
    verdict = verdict_map[match.group(1).lower()]
    after = search_space[match.end() :]
    lines = [line.strip() for line in after.splitlines() if line.strip()]
    summary = ""
    for line in lines:
        if line.startswith("#"):
            break
        summary = markdown_to_plain(line)
        if summary:
            break
    return verdict, summary or f"{match.group(1).title()} risk"


def extract_risk_summary(report_text: str) -> list[str]:
    body = ""
    for title, section_body in report_sections(report_text):
        if strip_heading_number(title).lower() == "risk summary":
            body = section_body
            break
    if not body:
        return []
    lines = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith(("- ", "* ")):
            continue
        normalized = markdown_to_plain(line[2:])
        if normalized:
            lines.append(normalized[:320])
    return lines[:12]


def extract_step_summaries(report_text: str) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    for title, body in report_sections(report_text):
        normalized_title = strip_heading_number(title).lower()
        if normalized_title in {"risk summary", "overall rating"}:
            continue
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        summary_line = ""
        for line in lines:
            if line.startswith(("🔴", "🟡", "🟢", "⚪")):
                summary_line = line
                break
        if not summary_line:
            for line in lines:
                if line.startswith("**") or re.match(r"^[A-Za-z0-9]", line):
                    summary_line = line
                    break
        if not summary_line:
            for line in lines:
                if not line.startswith(("|", "---", "### ")):
                    summary_line = line
                    break
        summary = markdown_to_plain(summary_line or "No summary extracted.")
        collected.append({"title": title, "summary": summary[:320]})
    return collected


def section_body(report_text: str, title_pattern: str) -> str:
    pattern = re.compile(title_pattern, flags=re.IGNORECASE)
    for title, body in report_sections(report_text):
        if pattern.search(strip_heading_number(title)):
            return body
    return ""


def detector_result(
    key: str,
    label: str,
    category: str,
    status: str,
    score: int,
    weight: int,
    summary: str,
    *,
    severity: str = "info",
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "category": category,
        "status": status,
        "score": max(0, min(100, int(score))),
        "weight": max(0, int(weight)),
        "severity": severity,
        "summary": summary[:320],
        "evidence": (evidence or [])[:5],
    }


def skipped_detector(key: str, label: str, category: str, weight: int, summary: str) -> dict[str, Any]:
    return detector_result(key, label, category, "skip", 0, weight, summary, severity="info")


def evidence_lines(body: str, patterns: list[str]) -> list[str]:
    lines: list[str] = []
    for raw_line in body.splitlines():
        plain = markdown_to_plain(raw_line)
        if not plain:
            continue
        lowered = plain.lower()
        if any(pattern in lowered for pattern in patterns):
            lines.append(plain[:220])
    return lines


def build_black_box_detector(overall_verdict: str, overall_summary: str) -> dict[str, Any]:
    if overall_verdict == "high":
        return detector_result(
            "black_box_security",
            "黑盒安全风险",
            "security",
            "fail",
            15,
            35,
            overall_summary or "原始黑盒审计判定为高风险。",
            severity="critical",
            evidence=[overall_summary] if overall_summary else [],
        )
    if overall_verdict == "medium":
        return detector_result(
            "black_box_security",
            "黑盒安全风险",
            "security",
            "warn",
            62,
            35,
            overall_summary or "原始黑盒审计判定为中风险或检测不完整。",
            severity="medium",
            evidence=[overall_summary] if overall_summary else [],
        )
    if overall_verdict == "low":
        return detector_result(
            "black_box_security",
            "黑盒安全风险",
            "security",
            "pass",
            95,
            35,
            overall_summary or "原始黑盒审计未发现显著攻击面风险。",
            severity="info",
            evidence=[overall_summary] if overall_summary else [],
        )
    return detector_result(
        "black_box_security",
        "黑盒安全风险",
        "security",
        "error",
        45,
        35,
        "原始黑盒审计未给出可识别总体风险等级。",
        severity="medium",
        evidence=[overall_summary] if overall_summary else [],
    )


def build_stream_protocol_detector(report_text: str, options: dict[str, Any]) -> dict[str, Any]:
    if options.get("skipStreamIntegrity"):
        return skipped_detector("stream_protocol", "流式协议一致性", "protocol", 15, "本次运行跳过了流式协议检测。")
    body = section_body(report_text, r"stream integrity")
    if not body:
        return skipped_detector("stream_protocol", "流式协议一致性", "protocol", 15, "报告中没有流式协议检测章节，按历史报告兼容跳过。")
    lowered = body.lower()
    evidence = evidence_lines(body, ["anomaly", "inconclusive", "unknown", "non-monotonic", "signature", "clean"])
    if "stream integrity anomaly detected" in lowered or "unknown sse" in lowered or "non-monotonic" in lowered:
        return detector_result(
            "stream_protocol",
            "流式协议一致性",
            "protocol",
            "fail",
            25,
            15,
            "流式响应违反关键 SSE/usage 协议不变量。",
            severity="critical",
            evidence=evidence,
        )
    if "inconclusive" in lowered or "could not be verified" in lowered:
        return detector_result(
            "stream_protocol",
            "流式协议一致性",
            "protocol",
            "warn",
            58,
            15,
            "流式协议检测未能得出确定结论。",
            severity="medium",
            evidence=evidence,
        )
    return detector_result(
        "stream_protocol",
        "流式协议一致性",
        "protocol",
        "pass",
        92,
        15,
        "流式响应结构、usage 单调性和模型字段未见显著异常。",
        severity="info",
        evidence=evidence,
    )


def build_tool_capability_detector(report_text: str, options: dict[str, Any]) -> dict[str, Any]:
    if options.get("skipToolSubstitution"):
        return skipped_detector("tool_capability", "工具调用完整性", "capability", 15, "本次运行跳过了工具调用检测。")
    body = section_body(report_text, r"tool-call|tool substitution")
    if not body:
        return skipped_detector("tool_capability", "工具调用完整性", "capability", 15, "报告中没有工具调用检测章节，按历史报告兼容跳过。")
    lowered = body.lower()
    evidence = evidence_lines(body, ["substitution", "inconclusive", "exact", "detected", "errored"])
    if "substitution detected" in lowered or "tool-call package substitution detected" in lowered:
        return detector_result(
            "tool_capability",
            "工具调用完整性",
            "capability",
            "fail",
            20,
            15,
            "检测到工具调用或包安装命令被中间层改写。",
            severity="critical",
            evidence=evidence,
        )
    if "inconclusive" in lowered or "every probe errored" in lowered:
        return detector_result(
            "tool_capability",
            "工具调用完整性",
            "capability",
            "warn",
            58,
            15,
            "工具调用检测未能确认完整透传。",
            severity="medium",
            evidence=evidence,
        )
    return detector_result(
        "tool_capability",
        "工具调用完整性",
        "capability",
        "pass",
        90,
        15,
        "工具调用改写探针未发现显著异常。",
        severity="info",
        evidence=evidence,
    )


def build_authenticity_detector(report_text: str) -> dict[str, Any]:
    identity_body = section_body(report_text, r"instruction|identity")
    latency_body = section_body(report_text, r"latency variance")
    body = "\n".join([identity_body, latency_body]).strip()
    if not body:
        return skipped_detector("model_authenticity", "模型真伪线索", "authenticity", 15, "报告中没有可用于模型真伪判断的身份或延迟指纹章节。")
    lowered = body.lower()
    evidence = evidence_lines(body, ["identity", "non-claude", "bimodal", "high-variance", "variable", "stable", "inconclusive"])
    if "claims non-claude identity" in lowered or "identity test failed" in lowered:
        return detector_result(
            "model_authenticity",
            "模型真伪线索",
            "authenticity",
            "fail",
            28,
            15,
            "模型身份响应与目标模型声明冲突。",
            severity="critical",
            evidence=evidence,
        )
    if "bimodal" in lowered or "high-variance" in lowered:
        return detector_result(
            "model_authenticity",
            "模型真伪线索",
            "authenticity",
            "warn",
            62,
            15,
            "延迟分布存在可能的多后端或路由不一致信号。",
            severity="medium",
            evidence=evidence,
        )
    if "inconclusive" in lowered:
        return detector_result(
            "model_authenticity",
            "模型真伪线索",
            "authenticity",
            "warn",
            58,
            15,
            "身份或指纹检测未能得出确定结论。",
            severity="medium",
            evidence=evidence,
        )
    return detector_result(
        "model_authenticity",
        "模型真伪线索",
        "authenticity",
        "pass",
        86,
        15,
        "身份响应和延迟指纹未见显著真伪冲突。",
        severity="info",
        evidence=evidence,
    )


def build_context_detector(report_text: str, options: dict[str, Any]) -> dict[str, Any]:
    if options.get("skipContext"):
        return skipped_detector("long_context", "长上下文真实性", "long_context", 10, "本次运行跳过了长上下文检测。")
    body = section_body(report_text, r"context length")
    if not body:
        return skipped_detector("long_context", "长上下文真实性", "long_context", 10, "报告中没有长上下文检测章节，按历史报告兼容跳过。")
    lowered = body.lower()
    evidence = evidence_lines(body, ["truncated", "boundary", "canary", "error", "ok"])
    if "truncated" in lowered:
        return detector_result(
            "long_context",
            "长上下文真实性",
            "long_context",
            "fail",
            35,
            10,
            "标准长上下文探针发现召回截断或上下文边界。",
            severity="high",
            evidence=evidence,
        )
    if "error" in lowered or "boundary" in lowered:
        return detector_result(
            "long_context",
            "长上下文真实性",
            "long_context",
            "warn",
            60,
            10,
            "长上下文探针存在错误或边界提示，需要复核。",
            severity="medium",
            evidence=evidence,
        )
    return detector_result(
        "long_context",
        "长上下文真实性",
        "long_context",
        "pass",
        88,
        10,
        "标准长上下文探针未发现明显截断。",
        severity="info",
        evidence=evidence,
    )


def build_error_surface_detector(report_text: str, options: dict[str, Any]) -> dict[str, Any]:
    if options.get("skipErrorLeakage"):
        return skipped_detector("error_surface", "错误面泄露", "security", 10, "本次运行跳过了错误响应泄露检测。")
    body = section_body(report_text, r"error response|error leakage")
    if not body:
        return skipped_detector("error_surface", "错误面泄露", "security", 10, "报告中没有错误响应泄露章节，按历史报告兼容跳过。")
    lowered = body.lower()
    evidence = evidence_lines(body, ["critical", "high", "medium", "leak", "inconclusive", "credential", "stack trace"])
    if "full api key echoed" in lowered or "critical" in lowered:
        return detector_result(
            "error_surface",
            "错误面泄露",
            "security",
            "fail",
            10,
            10,
            "错误响应疑似泄露凭据或关键上游信息。",
            severity="critical",
            evidence=evidence,
        )
    if "partial credential" in lowered or "high" in lowered:
        return detector_result(
            "error_surface",
            "错误面泄露",
            "security",
            "fail",
            35,
            10,
            "错误响应暴露上游或环境信息。",
            severity="high",
            evidence=evidence,
        )
    if "medium" in lowered or "stack trace" in lowered or "filesystem" in lowered:
        return detector_result(
            "error_surface",
            "错误面泄露",
            "security",
            "warn",
            62,
            10,
            "错误响应暴露调试信息或路径信息。",
            severity="medium",
            evidence=evidence,
        )
    if "inconclusive" in lowered:
        return detector_result(
            "error_surface",
            "错误面泄露",
            "security",
            "warn",
            58,
            10,
            "错误面检测未能覆盖到有效错误响应。",
            severity="medium",
            evidence=evidence,
        )
    return detector_result(
        "error_surface",
        "错误面泄露",
        "security",
        "pass",
        90,
        10,
        "错误响应未见显著敏感信息泄露。",
        severity="info",
        evidence=evidence,
    )


def category_verdict(detectors: list[dict[str, Any]], category: str) -> str:
    scoped = [item for item in detectors if item.get("category") == category and item.get("status") != "skip"]
    if not scoped:
        return "not_run"
    if any(item.get("severity") == "critical" or item.get("status") == "fail" for item in scoped):
        return "fail"
    if any(item.get("status") in {"warn", "error"} for item in scoped):
        return "warn"
    return "pass"


def compute_audit_score(detectors: list[dict[str, Any]]) -> int:
    scored = [item for item in detectors if item.get("status") != "skip" and item.get("weight", 0) > 0]
    if not scored:
        return 0
    weight_sum = sum(int(item.get("weight") or 0) for item in scored)
    if weight_sum <= 0:
        return 0
    weighted = sum(int(item.get("score") or 0) * int(item.get("weight") or 0) for item in scored)
    return int(round(weighted / weight_sum))


def combined_verdict(overall_verdict: str, audit_score: int, critical_findings: list[str]) -> str:
    if critical_findings:
        return "high"
    if overall_verdict == "inconclusive":
        return "inconclusive"
    if audit_score >= 82:
        return "low"
    if audit_score >= 55:
        return "medium"
    return "high"


def combined_reason(verdict: str, audit_score: int, critical_findings: list[str]) -> str:
    if critical_findings:
        return f"发现 {len(critical_findings)} 个 critical 级问题，总体结论上限锁定为高风险。"
    if verdict == "low":
        return f"综合评分 {audit_score}/100，黑盒安全、协议和能力检测未发现显著高危异常。"
    if verdict == "medium":
        return f"综合评分 {audit_score}/100，存在需要复核的中等风险或检测不完整项。"
    if verdict == "high":
        return f"综合评分 {audit_score}/100，检测结果显示高风险或核心能力异常。"
    return "原始报告未给出可确认结论，综合评分仅供参考。"


def build_enhanced_audit_fields(
    report_text: str,
    *,
    overall_verdict: str,
    overall_summary: str,
    model: str,
    effective_options: dict[str, Any] | None,
) -> dict[str, Any]:
    options = effective_options or {}
    detectors = [
        build_black_box_detector(overall_verdict, overall_summary),
        build_stream_protocol_detector(report_text, options),
        build_tool_capability_detector(report_text, options),
        build_authenticity_detector(report_text),
        build_context_detector(report_text, options),
        build_error_surface_detector(report_text, options),
    ]
    critical_findings = [
        str(item.get("summary") or item.get("label") or "")
        for item in detectors
        if item.get("severity") == "critical"
    ]
    audit_score = compute_audit_score(detectors)
    verdict = combined_verdict(overall_verdict, audit_score, critical_findings)
    run_mode = "standard_long_context" if not options.get("skipContext") else "standard"
    cost_notice = (
        "标准长上下文检测默认开启，会额外消耗 API 额度；检测按层推进，发现失败后停止更深层探针。"
        if not options.get("skipContext")
        else "本次运行关闭了长上下文检测，成本更低但无法验证上下文窗口真实性。"
    )
    if model.lower().startswith(("gpt-", "o1", "o3", "o4")):
        authenticity_note = "openai_behavioral"
    elif model.lower().startswith(("gemini-", "models/gemini-")):
        authenticity_note = "gemini_protocol"
    else:
        authenticity_note = "anthropic_behavioral"
    return {
        "audit_score": audit_score,
        "audit_verdict_reason": combined_reason(verdict, audit_score, critical_findings),
        "overall_verdict": verdict,
        "capability_verdict": category_verdict(detectors, "capability"),
        "protocol_verdict": category_verdict(detectors, "protocol"),
        "authenticity_verdict": category_verdict(detectors, "authenticity") if authenticity_note != "gemini_protocol" else category_verdict(detectors, "authenticity"),
        "long_context_verdict": category_verdict(detectors, "long_context"),
        "detector_results": detectors,
        "critical_findings": critical_findings,
        "run_mode": run_mode,
        "cost_notice": cost_notice,
    }


def enhanced_report_section(summary: StationAuditSummary) -> str:
    lines = [
        "",
        "---",
        "",
        "## 15. Unified Audit Score",
        "",
        f"**Score**: `{summary.audit_score}/100`",
        f"**Combined verdict**: `{summary.overall_verdict}`",
        f"**Run mode**: `{summary.run_mode}`",
        "",
        summary.audit_verdict_reason,
        "",
        f"Cost notice: {summary.cost_notice}",
        "",
        "| Detector | Category | Status | Score | Severity | Summary |",
        "|---|---|---:|---:|---|---|",
    ]
    for item in summary.detector_results:
        lines.append(
            "| {label} | {category} | {status} | {score} | {severity} | {summary} |".format(
                label=str(item.get("label") or "").replace("|", "\\|"),
                category=str(item.get("category") or "").replace("|", "\\|"),
                status=str(item.get("status") or "").replace("|", "\\|"),
                score=str(item.get("score") if item.get("status") != "skip" else "-"),
                severity=str(item.get("severity") or "").replace("|", "\\|"),
                summary=str(item.get("summary") or "").replace("|", "\\|"),
            )
        )
    if summary.critical_findings:
        lines.extend(["", "**Critical findings**:"])
        for finding in summary.critical_findings:
            lines.append(f"- {finding}")
    return "\n".join(lines) + "\n"


def build_summary(
    report_text: str,
    *,
    profile: str,
    model: str,
    audited_base_url: str,
    executed_at: str,
    report_path: Path,
    duration_ms: int = 0,
    effective_options: dict[str, Any] | None = None,
) -> StationAuditSummary:
    report_text = clean_legacy_audit_report_for_model(report_text, model)
    overall_verdict, overall_summary = parse_overall_verdict(report_text)
    enhanced = build_enhanced_audit_fields(
        report_text,
        overall_verdict=overall_verdict,
        overall_summary=overall_summary,
        model=model,
        effective_options=effective_options,
    )
    return StationAuditSummary(
        profile=profile,
        model=model,
        audited_base_url=audited_base_url,
        executed_at=executed_at,
        overall_verdict=enhanced["overall_verdict"],
        overall_summary=overall_summary,
        highlights=extract_risk_summary(report_text),
        step_summaries=extract_step_summaries(report_text),
        report_path=logical_data_path(report_path),
        tool_version=f"api-relay-audit@{ENGINE_COMMIT}",
        duration_ms=duration_ms,
        effective_options=effective_options or {},
        audit_score=enhanced["audit_score"],
        audit_verdict_reason=enhanced["audit_verdict_reason"],
        capability_verdict=enhanced["capability_verdict"],
        protocol_verdict=enhanced["protocol_verdict"],
        authenticity_verdict=enhanced["authenticity_verdict"],
        long_context_verdict=enhanced["long_context_verdict"],
        detector_results=enhanced["detector_results"],
        critical_findings=enhanced["critical_findings"],
        run_mode=enhanced["run_mode"],
        cost_notice=enhanced["cost_notice"],
    )


def build_audit_command(target: dict[str, Any], model: str, api_key: str, report_path: Path, options: AuditRunOptions) -> list[str]:
    command = [
        "python",
        str(ENGINE_PATH),
        "--key",
        api_key,
        "--url",
        target["auditBaseUrl"],
        "--model",
        model,
        "--profile",
        AUDIT_PROFILE,
        "--output",
        str(report_path),
        "--timeout",
        str(options.timeout),
        "--latency-probe-count",
        str(options.latency_probe_count),
    ]
    if options.warmup:
        command.extend(["--warmup", str(options.warmup)])
    if options.skip_infra:
        command.append("--skip-infra")
    if options.skip_context:
        command.append("--skip-context")
    if options.skip_tool_substitution:
        command.append("--skip-tool-substitution")
    if options.skip_error_leakage:
        command.append("--skip-error-leakage")
    if options.skip_stream_integrity:
        command.append("--skip-stream-integrity")
    if options.skip_infra_fingerprint:
        command.append("--skip-infra-fingerprint")
    if options.skip_latency_variance:
        command.append("--skip-latency-variance")
    if options.aggressive_error_probes:
        command.append("--aggressive-error-probes")
    return command


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def retention_days() -> int:
    raw = str(os.environ.get("AUDIT_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return value if value >= 1 else DEFAULT_RETENTION_DAYS


def retention_max_per_target() -> int:
    raw = str(os.environ.get("AUDIT_RETENTION_MAX_PER_TARGET", DEFAULT_RETENTION_MAX_PER_TARGET)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_MAX_PER_TARGET
    return value if value >= 1 else DEFAULT_RETENTION_MAX_PER_TARGET


def prune_audit_runs(*, now: datetime | None = None) -> list[str]:
    if not AUDIT_RUNS_DIR.exists():
        return []

    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=retention_days())
    max_per_target = retention_max_per_target()
    removed: list[str] = []

    for station_dir in sorted(path for path in AUDIT_RUNS_DIR.iterdir() if path.is_dir()):
        for model_dir in sorted(path for path in station_dir.iterdir() if path.is_dir()):
            run_dirs = [path for path in model_dir.iterdir() if path.is_dir()]
            dated: list[tuple[datetime, Path]] = []
            for run_dir in run_dirs:
                parsed = parse_run_dir_datetime(run_dir.name)
                if parsed is None:
                    parsed = datetime.fromtimestamp(run_dir.stat().st_mtime, tz=UTC)
                dated.append((parsed, run_dir))
            dated.sort(key=lambda item: item[0], reverse=True)
            keep_names = {path.name for _, path in dated[:max_per_target]}
            for run_time, run_dir in dated:
                if run_time >= cutoff and run_dir.name in keep_names:
                    continue
                shutil.rmtree(run_dir, ignore_errors=True)
                removed.append(str(run_dir))
    return removed


ProgressCallback = Callable[[dict[str, Any]], None]


def write_progress_event(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def emit_progress(progress: ProgressCallback | None, event_type: str, message: str, **payload: Any) -> None:
    if progress is None:
        return
    progress({"type": event_type, "message": message, **payload})


def engine_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }


def run_engine_command(
    command: list[str],
    *,
    secrets: list[str],
    progress: ProgressCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    if progress is None:
        return subprocess.run(
            command,
            cwd=APP_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=engine_env(),
        )

    process = subprocess.Popen(
        command,
        cwd=APP_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=engine_env(),
    )
    stream_queue: queue.Queue[tuple[str, str]] = queue.Queue()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def reader(name: str, stream: Any) -> None:
        try:
            for line in iter(stream.readline, ""):
                stream_queue.put((name, line))
        finally:
            stream.close()

    threads = [
        threading.Thread(target=reader, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=reader, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()

    while any(thread.is_alive() for thread in threads) or not stream_queue.empty():
        try:
            stream_name, line = stream_queue.get(timeout=0.1)
        except queue.Empty:
            continue
        if stream_name == "stdout":
            stdout_parts.append(line)
        else:
            stderr_parts.append(line)
        message = sanitize_text(line.rstrip("\r\n"), secrets)
        if message.strip():
            emit_progress(progress, "log", message, stream=stream_name)

    return_code = process.wait()
    for thread in threads:
        thread.join(timeout=1)
    return subprocess.CompletedProcess(command, return_code, stdout="".join(stdout_parts), stderr="".join(stderr_parts))


def build_run_payload(
    *,
    status: str,
    target: dict[str, Any],
    model: str,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    options: AuditRunOptions,
    command: list[str],
    secrets: list[str],
    completed: subprocess.CompletedProcess[str] | None = None,
    error: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "durationMs": duration_ms,
        "station": target["station"],
        "model": model,
        "profile": AUDIT_PROFILE,
        "auditedBaseUrl": target["auditBaseUrl"],
        "engineCommit": ENGINE_COMMIT,
        "effectiveOptions": options.to_payload(),
        "command": sanitized_command(command, secrets),
        "stdout": sanitize_text(completed.stdout if completed else "", secrets),
        "stderr": sanitize_text(completed.stderr if completed else "", secrets),
        "exitCode": completed.returncode if completed else None,
        "error": sanitize_text(error, secrets),
    }


def run_single_audit(
    target: dict[str, Any],
    model: str,
    *,
    timeout: int | None = None,
    api_key: str | None = None,
    options: AuditRunOptions | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    ensure_runtime_dirs()
    api_key = (api_key or os.environ.get(target["apiKeyEnv"], "")).strip()
    if not api_key:
        raise AuditConfigError(
            f"Environment variable '{target['apiKeyEnv']}' is required for station '{target['station']}'."
        )
    if target.get("profile") != AUDIT_PROFILE:
        raise AuditConfigError(f"Audit target '{target['station']}' uses unsupported profile '{target.get('profile')}'. Only 'general' is supported.")
    if model not in target["models"]:
        raise AuditConfigError(f"Model '{model}' is not configured for station '{target['station']}'.")

    base_options = options or target.get("options") or AuditRunOptions()
    if timeout is not None:
        base_options = AuditRunOptions(**{**base_options.__dict__, "timeout": timeout})

    started_at = now_iso()
    timestamp_dir = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = AUDIT_RUNS_DIR / target["station"] / slugify_model(model) / timestamp_dir
    report_path = run_dir / "report.md"
    summary_path = run_dir / "summary.json"
    run_path = run_dir / "run.json"
    secrets = [api_key]

    run_dir.mkdir(parents=True, exist_ok=True)
    command = build_audit_command(target, model, api_key, report_path, base_options)
    started = time.perf_counter()
    completed: subprocess.CompletedProcess[str] | None = None
    emit_progress(
        progress,
        "status",
        f"开始检测 {target['station']} / {model}",
        station=target["station"],
        model=model,
        auditedBaseUrl=target["auditBaseUrl"],
    )
    emit_progress(progress, "status", "启动本地审计引擎，等待检测输出。", station=target["station"], model=model)
    try:
        completed = run_engine_command(command, secrets=secrets, progress=progress)
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                sanitized_command(command, secrets),
                output=completed.stdout,
                stderr=completed.stderr,
            )
        report_text = report_path.read_text(encoding="utf-8")
        finished_at = now_iso()
        duration_ms = int((time.perf_counter() - started) * 1000)
        summary = build_summary(
            report_text,
            profile=AUDIT_PROFILE,
            model=model,
            audited_base_url=target["auditBaseUrl"],
            executed_at=started_at,
            report_path=report_path,
            duration_ms=duration_ms,
            effective_options=base_options.to_payload(),
        )
        report_path.write_text(report_text.rstrip() + enhanced_report_section(summary), encoding="utf-8")
        write_json(summary_path, summary.to_payload())
        write_json(
            run_path,
            build_run_payload(
                status="success",
                target=target,
                model=model,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                options=base_options,
                command=command,
                secrets=secrets,
                completed=completed,
            ),
        )
        emit_progress(
            progress,
            "status",
            f"检测完成，风险等级：{summary.overall_verdict}",
            station=target["station"],
            model=model,
            overallVerdict=summary.overall_verdict,
        )
        result = {
            "station": target["station"],
            "model": model,
            "profile": AUDIT_PROFILE,
            "auditedBaseUrl": target["auditBaseUrl"],
            "run": logical_data_path(run_path),
            "report": logical_data_path(report_path),
            "summary": logical_data_path(summary_path),
            "overallVerdict": summary.overall_verdict,
        }
        prune_audit_runs()
        return result
    except Exception as exc:
        finished_at = now_iso()
        duration_ms = int((time.perf_counter() - started) * 1000)
        write_json(
            run_path,
            build_run_payload(
                status="failed",
                target=target,
                model=model,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                options=base_options,
                command=command,
                secrets=secrets,
                completed=completed,
                error=str(exc),
            ),
        )
        emit_progress(
            progress,
            "error",
            sanitize_text(f"检测失败：{exc}", secrets),
            station=target["station"],
            model=model,
        )
        raise AuditConfigError(
            f"Audit failed for station '{target['station']}' model '{model}'. See {logical_data_path(run_path)}"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a pinned local relay audit and archive the result for a station.")
    parser.add_argument("--station", required=True, help="Configured station key from config/station_audit_targets.json")
    parser.add_argument("--model", help="Run audit for a specific configured model.")
    parser.add_argument("--all-models", action="store_true", help="Run the audit for every configured model on the station.")
    parser.add_argument("--include-disabled", action="store_true", help="Allow running a target marked as disabled.")
    parser.add_argument("--override-base-url", help=argparse.SUPPRESS)
    parser.add_argument("--request-api-key-env", default="", help=argparse.SUPPRESS)
    parser.add_argument("--ad-hoc-target", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--progress-jsonl", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=int, default=None, help="Per-request timeout forwarded to the audit engine.")
    parser.add_argument("--warmup", type=int, default=None, help="Send N benign requests before the audit.")
    parser.add_argument("--latency-probe-count", type=int, default=None, help="Number of Step 13 latency probes.")
    parser.add_argument("--skip-infra", action="store_true", help="Skip infrastructure recon.")
    parser.add_argument("--skip-context", action="store_true", help="Skip context length test.")
    parser.add_argument("--skip-tool-substitution", action="store_true", help="Skip tool-call substitution test.")
    parser.add_argument("--skip-error-leakage", action="store_true", help="Skip error leakage test.")
    parser.add_argument("--skip-stream-integrity", action="store_true", help="Skip stream integrity test.")
    parser.add_argument("--skip-infra-fingerprint", action="store_true", help="Skip infrastructure fingerprinting.")
    parser.add_argument("--skip-latency-variance", action="store_true", help="Skip latency variance fingerprinting.")
    parser.add_argument("--aggressive-error-probes", action="store_true", help="Enable high-cost oversized-context error probes.")
    args = parser.parse_args()
    if bool(args.model) == bool(args.all_models):
        parser.error("Specify exactly one of --model or --all-models.")
    return args


def ad_hoc_target_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if not args.model or not args.override_base_url or not args.request_api_key_env:
        raise AuditConfigError("--ad-hoc-target requires --model, --override-base-url and --request-api-key-env.")
    station = args.station
    return {
        "station": station,
        "auditBaseUrl": validate_absolute_url(args.override_base_url, station=station, field="overrideBaseUrl"),
        "profile": AUDIT_PROFILE,
        "models": [args.model],
        "defaultModel": args.model,
        "apiKeyEnv": args.request_api_key_env,
        "enabled": True,
        "options": AuditRunOptions(),
    }


def main() -> int:
    args = parse_args()
    progress = write_progress_event if args.progress_jsonl else None
    try:
        if args.ad_hoc_target:
            target = ad_hoc_target_from_args(args)
        else:
            target = get_target(args.station, include_disabled=args.include_disabled)
        if args.override_base_url:
            target = {**target, "auditBaseUrl": validate_absolute_url(args.override_base_url, station=args.station, field="overrideBaseUrl")}
        options = merge_option_overrides(target.get("options") or AuditRunOptions(), args)
        api_key = os.environ.get(args.request_api_key_env or "", "").strip() if args.request_api_key_env else None
        models = [args.model] if args.model else list(target["models"])
        emit_progress(progress, "status", f"已解析检测目标：{target['station']}，模型 {', '.join(models)}。")
        results = [run_single_audit(target, model, options=options, api_key=api_key, progress=progress) for model in models]
        if args.progress_jsonl:
            write_progress_event({"type": "result", "executed": results})
        else:
            print(json.dumps({"executed": results}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        if args.progress_jsonl:
            write_progress_event({"type": "error", "message": sanitize_text(exc)})
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
