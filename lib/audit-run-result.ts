import type { HomeAuditRunResponse, StationAuditHistoryItem, StationAuditSummary } from "./types";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function runIdFromReportPath(reportPath: string) {
  const parts = reportPath.replace(/\\/g, "/").split("/").filter(Boolean);
  const reportIndex = parts.lastIndexOf("report.md");
  return reportIndex > 0 ? parts[reportIndex - 1] : "";
}

function isAuditSummary(value: unknown): value is StationAuditSummary {
  const summary = asRecord(value);
  return Boolean(
    summary &&
      stringValue(summary.profile) === "general" &&
      stringValue(summary.model) &&
      stringValue(summary.executedAt) &&
      stringValue(summary.overallVerdict) &&
      stringValue(summary.reportPath),
  );
}

export function auditHistoryItemFromRunResult(result: HomeAuditRunResponse | unknown): StationAuditHistoryItem | null {
  const payload = asRecord(result);
  if (!payload || !isAuditSummary(payload.summary)) {
    return null;
  }

  const summary = payload.summary;
  const historyItem = asRecord(payload.historyItem);
  const stationKey = stringValue(historyItem?.stationKey) || stringValue(payload.station);
  const runId = stringValue(historyItem?.runId) || runIdFromReportPath(summary.reportPath) || summary.executedAt;
  if (!stationKey || !runId) {
    return null;
  }

  return {
    ...summary,
    stationKey,
    stationLabel: stringValue(historyItem?.stationLabel) || stationKey,
    stationUrl: stringValue(historyItem?.stationUrl) || summary.auditedBaseUrl,
    runId,
    reportUrl:
      stringValue(historyItem?.reportUrl) ||
      stringValue(payload.reportUrl) ||
      `/api/audit-report?station=${encodeURIComponent(stationKey)}&model=${encodeURIComponent(summary.model)}&run=${encodeURIComponent(runId)}`,
  };
}
