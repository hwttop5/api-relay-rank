"use client";

import { CheckCircle2, Clock3, ExternalLink, KeyRound, Loader2, Search, ShieldAlert, Tag, TerminalSquare } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type UIEvent } from "react";

import { auditHistoryItemFromRunResult } from "@/lib/audit-run-result";
import { formatAuditVerdict, formatDateTime } from "@/lib/format";
import type { AuditModelOption, HomeAuditRunRequest, HomeAuditRunResponse } from "@/lib/types";

export const AUDIT_MODEL_OPTIONS: AuditModelOption[] = [
  { label: "Opus 4.8", value: "claude-opus-4-8", badge: "NEW" },
  { label: "Opus 4.7", value: "claude-opus-4-7" },
  { label: "Opus 4.6", value: "claude-opus-4-6" },
  { label: "GPT 5.5", value: "gpt-5.5" },
  { label: "GPT 5.4", value: "gpt-5.4" },
  { label: "Gemini 3.5 Flash", value: "gemini-3.5-flash" },
];

const DEFAULT_AUDIT_MODEL = "claude-opus-4-8";
const MAX_LOG_LINES = 300;
const TERMINAL_BOTTOM_THRESHOLD_PX = 48;

type AuditState = "idle" | "running" | "success" | "error";
type AuditLogKind = "status" | "log" | "error" | "complete";

interface AuditLogLine {
  id: number;
  kind: AuditLogKind;
  message: string;
  stream?: string;
}

interface AuditStreamEvent {
  type?: "status" | "log" | "error" | "complete";
  message?: string;
  stream?: string;
  result?: HomeAuditRunResponse;
}

function statusCopy(state: AuditState) {
  if (state === "running") {
    return "检测中";
  }
  if (state === "success") {
    return "检测完成";
  }
  if (state === "error") {
    return "检测失败";
  }
  return "等待检测";
}

function logPrefix(line: AuditLogLine) {
  if (line.kind === "error") {
    return "ERR";
  }
  if (line.kind === "complete") {
    return "OK";
  }
  if (line.stream === "stderr") {
    return "STDERR";
  }
  if (line.kind === "log") {
    return "RUN";
  }
  return "SYS";
}

export function HomeAuditLauncher({ onAuditComplete }: { onAuditComplete?: (result: HomeAuditRunResponse) => void }) {
  const router = useRouter();
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(DEFAULT_AUDIT_MODEL);
  const [state, setState] = useState<AuditState>("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<HomeAuditRunResponse | null>(null);
  const [logLines, setLogLines] = useState<AuditLogLine[]>([]);
  const logIdRef = useRef(0);
  const terminalBodyRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const scrollFrameRef = useRef<number | null>(null);

  const canSubmit = apiBaseUrl.trim().length > 0 && apiKey.trim().length > 0 && model.length > 0 && state !== "running";

  function appendLog(kind: AuditLogKind, message: string, stream?: string) {
    const normalized = message.trim();
    if (!normalized) {
      return;
    }
    logIdRef.current += 1;
    const line = { id: logIdRef.current, kind, message: normalized, stream };
    setLogLines((current) => [...current, line].slice(-MAX_LOG_LINES));
  }

  function scrollTerminalToBottom() {
    const terminalBody = terminalBodyRef.current;
    if (!terminalBody) {
      return;
    }
    terminalBody.scrollTop = terminalBody.scrollHeight;
  }

  function handleStreamLine(line: string) {
    const text = line.trim();
    if (!text) {
      return false;
    }

    let event: AuditStreamEvent;
    try {
      event = JSON.parse(text) as AuditStreamEvent;
    } catch {
      appendLog("log", text, "stdout");
      return false;
    }

    if (event.type === "complete") {
      const historyItem = auditHistoryItemFromRunResult(event.result);
      if (!event.result || !event.result.summary || !historyItem) {
        appendLog("error", "检测完成事件缺少审计摘要，无法刷新历史记录。");
        throw new Error("检测完成事件缺少审计摘要，无法刷新历史记录。");
      }
      const completeResult = { ...event.result, historyItem };
      appendLog("complete", event.message || "检测完成。");
      setResult(completeResult);
      setState("success");
      setMessage("检测完成，结果已按站点归档。");
      setApiKey("");
      onAuditComplete?.(completeResult);
      router.refresh();
      return true;
    }

    if (event.type === "error") {
      appendLog("error", event.message || "检测失败。");
      throw new Error(event.message || "检测失败。");
    }

    const kind: AuditLogKind = event.type === "log" ? "log" : "status";
    appendLog(kind, event.message || text, event.stream);
    return false;
  }

  async function startAudit() {
    if (!canSubmit) {
      return;
    }

    const request: HomeAuditRunRequest = {
      apiBaseUrl: apiBaseUrl.trim(),
      apiKey: apiKey.trim(),
      model,
    };

    setState("running");
    setMessage("正在执行 /models 预探测与主动黑盒审计，完成后会自动刷新站点数据。");
    setResult(null);
    setLogLines([]);
    logIdRef.current = 0;
    shouldStickToBottomRef.current = true;
    appendLog("status", "准备提交检测任务：先校验模型可用性，再运行标准长上下文探针。");

    try {
      const response = await fetch("/api/station-audit/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.error || "检测失败。");
      }
      if (!response.body) {
        throw new Error("检测连接未返回进度流。");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          completed = handleStreamLine(line) || completed;
        }
      }

      buffer += decoder.decode();
      if (buffer.trim()) {
        completed = handleStreamLine(buffer) || completed;
      }
      if (!completed) {
        throw new Error("检测进度流提前结束。");
      }
    } catch (error) {
      setState("error");
      const errorMessage = error instanceof Error ? error.message : "检测失败。";
      setMessage(errorMessage);
      appendLog("error", errorMessage);
    }
  }

  function updateTerminalStickState(event: UIEvent<HTMLDivElement>) {
    const target = event.currentTarget;
    shouldStickToBottomRef.current =
      target.scrollHeight - target.scrollTop - target.clientHeight < TERMINAL_BOTTOM_THRESHOLD_PX;
  }

  useEffect(() => {
    if (!shouldStickToBottomRef.current) {
      return;
    }
    if (scrollFrameRef.current !== null) {
      cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollTerminalToBottom();
      scrollFrameRef.current = null;
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [logLines.length]);

  return (
    <section className="section home-audit-section">
      <div className="home-audit-head">
        <div>
          <h1 className="home-audit-title">安全审计</h1>
          <p className="section-desc">输入中转站 API 地址和临时 API Key，提交前会先做 /models 预探测，再执行标准长上下文安全检测。</p>
        </div>
        <div className="section-head-actions home-audit-actions">
          <span className={`chip ${state === "success" ? "chip-accent" : state === "error" ? "chip-danger" : state === "running" ? "chip-blue" : ""}`}>
            {statusCopy(state)}
          </span>
        </div>
      </div>

      <div className="home-audit-body">
        <div className="home-audit-fields">
          <label className="home-audit-field">
            <span>API 接口地址</span>
            <div className="home-audit-input-wrap">
              <Search size={18} />
              <input
                value={apiBaseUrl}
                onChange={(event) => setApiBaseUrl(event.target.value)}
                placeholder="https://api.anthropic.com"
                autoComplete="off"
                inputMode="url"
              />
              <Tag size={17} />
            </div>
          </label>

          <label className="home-audit-field">
            <span>API KEY</span>
            <div className="home-audit-input-wrap">
              <KeyRound size={18} />
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="sk-..."
                autoComplete="off"
              />
            </div>
          </label>
        </div>

        <div className="home-audit-models">
          <p className="home-audit-label">目标模型</p>
          <div className="home-audit-model-grid">
            {AUDIT_MODEL_OPTIONS.map((option) => {
              const active = option.value === model;
              return (
                <button
                  type="button"
                  key={option.value}
                  className={active ? "home-audit-model-card is-active" : "home-audit-model-card"}
                  onClick={() => setModel(option.value)}
                  aria-pressed={active}
                >
                  {option.badge ? <span className="home-audit-model-badge">{option.badge}</span> : null}
                  <strong>{option.label}</strong>
                  <span>{option.value}</span>
                  {active ? <CheckCircle2 size={18} /> : null}
                </button>
              );
            })}
          </div>
        </div>

        <div className="home-audit-footer">
          <div className="home-audit-note">
            <Clock3 size={16} />
            <p>
              API Key 仅用于本次本地检测，不写入配置、localStorage、报告或页面 URL。标准长上下文检测默认开启，可能增加 API
              额度与耗时；探针按层推进，失败后会停止更深层检测。
            </p>
          </div>
          <button type="button" className="home-audit-submit" disabled={!canSubmit} onClick={startAudit}>
            {state === "running" ? <Loader2 size={20} className="spin-icon" /> : null}
            {state === "running" ? "检测中" : "开始检测"}
          </button>
        </div>

        {logLines.length > 0 ? (
          <div className="home-audit-terminal" role="log" aria-live="polite">
            <div className="home-audit-terminal-head">
              <span>
                <TerminalSquare size={16} />
                检测进度
              </span>
              <span>{logLines.length} 行</span>
            </div>
            <div className="home-audit-terminal-body" ref={terminalBodyRef} onScroll={updateTerminalStickState}>
              {logLines.map((line) => (
                <div className={`home-audit-log-row home-audit-log-${line.kind}${line.stream === "stderr" ? " home-audit-log-stderr" : ""}`} key={line.id}>
                  <span className="home-audit-log-prefix">{logPrefix(line)}</span>
                  <span className="home-audit-log-message">{line.message}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {message ? (
          <div className={state === "error" ? "home-audit-result home-audit-result-error" : "home-audit-result"}>
            {state === "error" ? <ShieldAlert size={18} /> : <CheckCircle2 size={18} />}
            <div>
              <p>{message}</p>
              {result ? (
                <div className="home-audit-result-links">
                  <span>
                    {typeof result.summary.auditScore === "number" ? `${result.summary.auditScore}/100 · ` : ""}
                    {formatAuditVerdict(result.summary.overallVerdict)} · {formatDateTime(result.summary.executedAt)}
                  </span>
                  <a href={result.stationUrl} className="station-link inline-actions">
                    查看审计详情
                    <ExternalLink size={14} />
                  </a>
                  <a href={result.reportUrl} target="_blank" rel="noreferrer" className="station-link inline-actions">
                    原始报告
                    <ExternalLink size={14} />
                  </a>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
