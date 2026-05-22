#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


SCRIPT_PATH = Path(__file__).resolve()
APP_ROOT = SCRIPT_PATH.parents[1]
DATA_DIR = APP_ROOT / "data"
AUDIT_RUNS_DIR = DATA_DIR / "_audit_runs"
CONFIG_PATH = APP_ROOT / "config" / "station_audit_targets.json"
ENGINE_PATH = APP_ROOT / "vendor" / "api_relay_audit" / "audit.py"
ENGINE_COMMIT = "2d6bc1431cc196d64a22e8aa515094ad9acb7042"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_LATENCY_PROBE_COUNT = 10
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 3600
MIN_WARMUP = 0
MAX_WARMUP = 20
MIN_LATENCY_PROBE_COUNT = 3
MAX_LATENCY_PROBE_COUNT = 50
AUDIT_PROFILE = "general"

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
        }


def slugify_model(model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model.strip()).strip("-")
    return slug or "model"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    overall_verdict, overall_summary = parse_overall_verdict(report_text)
    return StationAuditSummary(
        profile=profile,
        model=model,
        audited_base_url=audited_base_url,
        executed_at=executed_at,
        overall_verdict=overall_verdict,
        overall_summary=overall_summary,
        highlights=extract_risk_summary(report_text),
        step_summaries=extract_step_summaries(report_text),
        report_path=str(report_path.relative_to(APP_ROOT)).replace("\\", "/"),
        tool_version=f"api-relay-audit@{ENGINE_COMMIT}",
        duration_ms=duration_ms,
        effective_options=effective_options or {},
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
        return {
            "station": target["station"],
            "model": model,
            "profile": AUDIT_PROFILE,
            "auditedBaseUrl": target["auditBaseUrl"],
            "run": str(run_path.relative_to(APP_ROOT)).replace("\\", "/"),
            "report": str(report_path.relative_to(APP_ROOT)).replace("\\", "/"),
            "summary": str(summary_path.relative_to(APP_ROOT)).replace("\\", "/"),
            "overallVerdict": summary.overall_verdict,
        }
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
        raise AuditConfigError(f"Audit failed for station '{target['station']}' model '{model}'. See {run_path.relative_to(APP_ROOT)}") from exc


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
