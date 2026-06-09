import { CheckCircle2, ExternalLink, FileText, ShieldAlert } from "lucide-react";

import { localizeAuditText } from "@/lib/audit-localization";
import { formatAuditVerdict, formatDateTime } from "@/lib/format";
import type { StationAuditDetectorResult, StationAuditSummary, StationRecord } from "@/lib/types";

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

function detectorStatusLabel(status: string) {
  if (status === "pass") {
    return "通过";
  }
  if (status === "warn") {
    return "复核";
  }
  if (status === "fail") {
    return "失败";
  }
  if (status === "skip") {
    return "跳过";
  }
  return "异常";
}

function dimensionLabel(value: string | undefined) {
  if (value === "pass") {
    return "通过";
  }
  if (value === "warn") {
    return "复核";
  }
  if (value === "fail") {
    return "失败";
  }
  if (value === "not_run") {
    return "未跑";
  }
  return "未定";
}

const DETECTOR_STATUS_ORDER: Record<string, number> = {
  fail: 0,
  error: 0,
  warn: 1,
  pass: 2,
  skip: 3,
};

function compareDetectorRisk(a: StationAuditDetectorResult, b: StationAuditDetectorResult) {
  const statusDiff = (DETECTOR_STATUS_ORDER[a.status] ?? 1) - (DETECTOR_STATUS_ORDER[b.status] ?? 1);
  if (statusDiff !== 0) {
    return statusDiff;
  }
  return a.label.localeCompare(b.label, "zh-CN");
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
  const detectorRows = [...(latest.detectorResults ?? [])].sort(compareDetectorRisk);
  const criticalCount = latest.criticalFindings?.length ?? 0;

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
              <span className="mono">{typeof latest.auditScore === "number" ? `${latest.auditScore}/100` : latest.model}</span>
            </div>
            <h3>最新审计结论</h3>
            <p>{latest.auditVerdictReason || overallSummary || "审计报告未给出总体摘要。"}</p>
            {criticalCount > 0 ? <p className="station-audit-critical">Critical findings：{criticalCount} 个</p> : null}
            <div className="station-audit-meta">
              <span>{formatDateTime(latest.executedAt)}</span>
              <span>{latest.runMode || "standard"}</span>
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

        <div className="station-audit-summary-card station-audit-dimensions-card">
          <h3>检测维度</h3>
          <div className="station-audit-dimension-grid">
            <span>协议 {dimensionLabel(latest.protocolVerdict)}</span>
            <span>能力 {dimensionLabel(latest.capabilityVerdict)}</span>
            <span>真伪 {dimensionLabel(latest.authenticityVerdict)}</span>
            <span>长上下文 {dimensionLabel(latest.longContextVerdict)}</span>
          </div>
          {latest.costNotice ? <p>{latest.costNotice}</p> : null}
        </div>

        {detectorRows.length > 0 ? (
          <div className="station-audit-detector-grid">
            {detectorRows.map((detector) => (
              <div className="detail-card station-audit-detector-card" key={detector.key}>
                <div className="station-audit-card-head">
                  <h3>{detector.label}</h3>
                  <span className={`audit-detector-status audit-detector-${detector.status}`}>{detectorStatusLabel(detector.status)}</span>
                </div>
                <p>{detector.summary}</p>
                <div className="station-audit-meta">
                  <span>{detector.category}</span>
                  <span>{typeof detector.score === "number" ? `${detector.score}/100` : "-"}</span>
                  <span>{detector.severity || "info"}</span>
                </div>
              </div>
            ))}
          </div>
        ) : null}

        {stepSummaries.length > 0 ? (
          <div className="station-audit-raw-steps">
            <h3 className="station-audit-subtitle">原始步骤摘要</h3>
            <div className="station-audit-step-grid">
              {stepSummaries.map((step) => (
                <div className="detail-card station-audit-step-card" key={step.title}>
                  <h3>{step.title}</h3>
                  <p>{step.summary}</p>
                </div>
              ))}
            </div>
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
