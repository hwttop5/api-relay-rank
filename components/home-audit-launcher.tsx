"use client";

import { CheckCircle2, Clock3, ExternalLink, KeyRound, Loader2, Search, ShieldAlert, Tag } from "lucide-react";
import { useState } from "react";

import { formatAuditVerdict, formatDateTime } from "@/lib/format";
import type { AuditModelOption, HomeAuditRunRequest, HomeAuditRunResponse } from "@/lib/types";

export const AUDIT_MODEL_OPTIONS: AuditModelOption[] = [
  { label: "Opus 4.7", value: "claude-opus-4-7" },
  { label: "Opus 4.6", value: "claude-opus-4-6" },
  { label: "Sonnet 4.6", value: "claude-sonnet-4-6" },
  { label: "GPT 5.5", value: "gpt-5.5", badge: "NEW" },
  { label: "GPT 5.4", value: "gpt-5.4" },
  { label: "Gemini 3.1 Pro", value: "gemini-3.1-pro-preview" },
];

const DEFAULT_AUDIT_MODEL = "gpt-5.5";

type AuditState = "idle" | "running" | "success" | "error";

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

export function HomeAuditLauncher() {
  const [apiBaseUrl, setApiBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(DEFAULT_AUDIT_MODEL);
  const [state, setState] = useState<AuditState>("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<HomeAuditRunResponse | null>(null);

  const canSubmit = apiBaseUrl.trim().length > 0 && apiKey.trim().length > 0 && model.length > 0 && state !== "running";

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
    setMessage("正在执行主动黑盒审计，完成后会自动刷新站点数据。");
    setResult(null);

    try {
      const response = await fetch("/api/station-audit/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.error || "检测失败。");
      }
      setResult(payload as HomeAuditRunResponse);
      setState("success");
      setMessage("检测完成，结果已按站点归档。");
      setApiKey("");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "检测失败。");
    }
  }

  return (
    <section className="section home-audit-section">
      <div className="home-audit-head">
        <div>
          <h1 className="home-audit-title">安全审计</h1>
          <p className="section-desc">输入中转站 API 地址和临时 API Key，选择模型后开始安全检测。</p>
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
            <p>API Key 仅用于本次本地检测，不写入配置、localStorage、报告或页面 URL。已收录站点会自动匹配，未收录站点会按域名新建审计记录。</p>
          </div>
          <button type="button" className="home-audit-submit" disabled={!canSubmit} onClick={startAudit}>
            {state === "running" ? <Loader2 size={20} className="spin-icon" /> : null}
            {state === "running" ? "检测中" : "开始检测"}
          </button>
        </div>

        {message ? (
          <div className={state === "error" ? "home-audit-result home-audit-result-error" : "home-audit-result"}>
            {state === "error" ? <ShieldAlert size={18} /> : <CheckCircle2 size={18} />}
            <div>
              <p>{message}</p>
              {result ? (
                <div className="home-audit-result-links">
                  <span>{formatAuditVerdict(result.summary.overallVerdict)} · {formatDateTime(result.summary.executedAt)}</span>
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
