import { CheckCircle2, ExternalLink, FileText, ShieldAlert } from "lucide-react";

import { localizeAuditText } from "@/lib/audit-localization";
import { formatAuditVerdict, formatDateTime } from "@/lib/format";
import type { StationAuditSummary, StationRecord } from "@/lib/types";

function reportUrl(stationKey: string, model: string) {
  return `/api/audit-report?station=${encodeURIComponent(stationKey)}&model=${encodeURIComponent(model)}`;
}

function verdictClass(verdict: StationAuditSummary["overallVerdict"]) {
  if (verdict === "high") {
    return "audit-verdict-high";
  }
  if (verdict === "medium") {
    return "audit-verdict-medium";
  }
  if (verdict === "low") {
    return "audit-verdict-low";
  }
  return "audit-verdict-inconclusive";
}

export function StationAuditSummaryPanel({ station }: { station: StationRecord }) {
  const auditRows = station.audits?.latestByModel ?? [];
  if (auditRows.length === 0) {
    return null;
  }

  const latest = auditRows[0];
  const latestReportUrl = reportUrl(station.key, latest.model);
  const stepSummaries = latest.stepSummaries.slice(0, 4).map((step) => ({
    title: localizeAuditText(step.title),
    summary: localizeAuditText(step.summary),
  }));
  const highlights = latest.highlights.slice(0, 5).map(localizeAuditText);
  const overallSummary = localizeAuditText(latest.overallSummary);

  return (
    <section id="audit" className="section station-audit-summary-section">
      <div className="section-head">
        <div>
          <h2 className="section-title">安全审计</h2>
          <p className="section-desc">展示最近一次主动黑盒审计摘要；完整证据保留在原始 Markdown 报告中。</p>
        </div>
        <a href={latestReportUrl} target="_blank" rel="noreferrer" className="tiny-button detail-topbar-button">
          <FileText size={13} />
          原始报告
        </a>
      </div>
      <div className="section-body">
        <div className="station-audit-summary-grid">
          <div className="station-audit-summary-card station-audit-primary-card">
            <div className="station-audit-card-head">
              <span className={`audit-verdict-pill ${verdictClass(latest.overallVerdict)}`}>{formatAuditVerdict(latest.overallVerdict)}</span>
              <span className="mono">{latest.model}</span>
            </div>
            <h3>最新审计结论</h3>
            <p>{overallSummary || "审计报告未给出总体摘要。"}</p>
            <div className="station-audit-meta">
              <span>{formatDateTime(latest.executedAt)}</span>
              <span>{latest.auditedBaseUrl}</span>
            </div>
          </div>

          <div className="station-audit-summary-card">
            <h3>关键结论</h3>
            {highlights.length > 0 ? (
              <ul className="station-audit-list">
                {highlights.map((item) => (
                  <li key={item}>
                    <CheckCircle2 size={14} />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>暂无关键结论摘要。</p>
            )}
          </div>
        </div>

        {stepSummaries.length > 0 ? (
          <div className="station-audit-step-grid">
            {stepSummaries.map((step) => (
              <div className="detail-card station-audit-step-card" key={step.title}>
                <h3>{step.title}</h3>
                <p>{step.summary}</p>
              </div>
            ))}
          </div>
        ) : null}

        <div className="station-audit-models">
          <div className="footer-note">已归档模型：{auditRows.map((item) => item.model).join("、")}</div>
          <div className="station-audit-model-links">
            {auditRows.map((summary) => (
              <a key={summary.model} href={reportUrl(station.key, summary.model)} target="_blank" rel="noreferrer" className="station-audit-model-link">
                <ShieldAlert size={14} />
                <span>{summary.model}</span>
                <span>{formatAuditVerdict(summary.overallVerdict)}</span>
                <ExternalLink size={13} />
              </a>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
