import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import { hasDatabaseUrl, readStationAuditRunRows, type StationAuditRunRow } from "./postgres";
import { AUDIT_RUNS_ROOT, resolveLogicalDataPath } from "./runtime-paths";
import type { AuditVerdict, SiteData, StationAuditHistoryItem, StationAuditSummary } from "./types";

const AUDIT_SEGMENT_PATTERN = /^[A-Za-z0-9._-]+$/;
const VALID_VERDICTS = new Set<AuditVerdict>(["low", "medium", "high", "inconclusive"]);

function isSafeAuditSegment(value: string) {
  return AUDIT_SEGMENT_PATTERN.test(value) && value !== "." && value !== "..";
}

export function resolveAuditRunReportPath(stationKey: string, model: string, runId: string) {
  if (![stationKey, model, runId].every(isSafeAuditSegment)) {
    return null;
  }

  const root = path.resolve(AUDIT_RUNS_ROOT);
  const filePath = path.resolve(root, stationKey, model, runId, "report.md");
  if (!filePath.startsWith(root + path.sep)) {
    return null;
  }
  return filePath;
}

export function resolveArchivedReportPath(reportPath: string) {
  const auditRoot = path.resolve(AUDIT_RUNS_ROOT);
  const filePath = path.resolve(resolveLogicalDataPath(reportPath));
  if (!filePath.startsWith(auditRoot + path.sep)) {
    return null;
  }
  return filePath;
}

function normalizeAuditVerdict(value: unknown): AuditVerdict {
  const verdict = String(value || "").trim().toLowerCase();
  return VALID_VERDICTS.has(verdict as AuditVerdict) ? (verdict as AuditVerdict) : "inconclusive";
}

function normalizeAuditSummary(payload: unknown): StationAuditSummary | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const item = payload as Record<string, unknown>;
  const profile = String(item.profile || "").trim();
  const model = String(item.model || "").trim();
  const executedAt = String(item.executedAt || "").trim();
  const reportPath = String(item.reportPath || "").trim();
  const runStatus = String(item.runStatus || "success").trim();
  if (profile !== "general" || !model || !executedAt || !reportPath || runStatus !== "success") {
    return null;
  }

  const stepSummaries = Array.isArray(item.stepSummaries)
    ? item.stepSummaries.flatMap((step) => {
        if (!step || typeof step !== "object") {
          return [];
        }
        const rawStep = step as Record<string, unknown>;
        const title = String(rawStep.title || "").trim();
        const summary = String(rawStep.summary || "").trim();
        return title && summary ? [{ title, summary }] : [];
      })
    : [];

  const summary: StationAuditSummary = {
    profile: "general",
    model,
    auditedBaseUrl: String(item.auditedBaseUrl || "").trim(),
    executedAt,
    overallVerdict: normalizeAuditVerdict(item.overallVerdict),
    overallSummary: String(item.overallSummary || "").trim(),
    highlights: Array.isArray(item.highlights) ? item.highlights.map((value) => String(value || "").trim()).filter(Boolean) : [],
    stepSummaries,
    reportPath,
    toolVersion: String(item.toolVersion || "").trim(),
  };

  if (typeof item.durationMs === "number" && Number.isFinite(item.durationMs)) {
    summary.durationMs = item.durationMs;
  }
  const engineCommit = String(item.engineCommit || "").trim();
  if (engineCommit) {
    summary.engineCommit = engineCommit;
  }
  if (item.effectiveOptions && typeof item.effectiveOptions === "object" && !Array.isArray(item.effectiveOptions)) {
    summary.effectiveOptions = item.effectiveOptions as Record<string, unknown>;
  }
  return summary;
}

function auditSortTime(value: string) {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

async function safeListDirectories(folder: string) {
  try {
    const entries = await readdir(folder, { withFileTypes: true });
    return entries.filter((entry) => entry.isDirectory() && isSafeAuditSegment(entry.name)).map((entry) => entry.name);
  } catch {
    return [];
  }
}

async function readAuditSummary(summaryPath: string) {
  try {
    return normalizeAuditSummary(JSON.parse(await readFile(summaryPath, "utf8")));
  } catch {
    return null;
  }
}

function parseAuditSummaryPayload(payload: StationAuditRunRow["summary"]) {
  if (typeof payload === "string") {
    try {
      return normalizeAuditSummary(JSON.parse(payload));
    } catch {
      return null;
    }
  }
  return normalizeAuditSummary(payload);
}

function publicUrlHost(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return "";
    }
    return url.hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "";
  }
}

function hostsReferToSameSite(left: string, right: string) {
  return left === right || left.endsWith(`.${right}`) || right.endsWith(`.${left}`);
}

function findStationByAuditUrl(siteData: SiteData, auditedBaseUrl: string) {
  const auditedHost = publicUrlHost(auditedBaseUrl);
  if (!auditedHost) {
    return null;
  }
  return siteData.stations.find((station) => {
    const stationHost = publicUrlHost(station.url);
    return stationHost && hostsReferToSameSite(auditedHost, stationHost);
  });
}

function siteDataSource() {
  return process.env.SITE_DATA_SOURCE?.trim().toLowerCase() || "json";
}

function allowFileFallback() {
  return process.env.SITE_DATA_ALLOW_FILE_FALLBACK === "1";
}

function postgresAuditHistoryEnabled() {
  return siteDataSource() === "postgres" && hasDatabaseUrl();
}

async function readFileAuditHistory(siteData: SiteData): Promise<StationAuditHistoryItem[]> {
  const stationMap = new Map(siteData.stations.map((station) => [station.key, station]));
  const history: StationAuditHistoryItem[] = [];

  for (const stationKey of await safeListDirectories(AUDIT_RUNS_ROOT)) {
    const stationRoot = path.join(AUDIT_RUNS_ROOT, stationKey);
    for (const modelDir of await safeListDirectories(stationRoot)) {
      const modelRoot = path.join(stationRoot, modelDir);
      for (const runId of await safeListDirectories(modelRoot)) {
        const summary = await readAuditSummary(path.join(modelRoot, runId, "summary.json"));
        if (!summary) {
          continue;
        }
        const station = stationMap.get(stationKey) || findStationByAuditUrl(siteData, summary.auditedBaseUrl);
        const displayStationKey = station?.key || stationKey;
        history.push({
          ...summary,
          stationKey: displayStationKey,
          stationLabel: station?.label || stationKey,
          stationUrl: station?.url || summary.auditedBaseUrl,
          runId,
          reportUrl: `/api/audit-report?station=${encodeURIComponent(stationKey)}&model=${encodeURIComponent(modelDir)}&run=${encodeURIComponent(runId)}`,
        });
      }
    }
  }

  history.sort((a, b) => auditSortTime(b.executedAt) - auditSortTime(a.executedAt));
  return history;
}

async function readPostgresAuditHistory(siteData: SiteData): Promise<StationAuditHistoryItem[]> {
  const stationMap = new Map(siteData.stations.map((station) => [station.key, station]));
  const history: StationAuditHistoryItem[] = [];

  for (const row of await readStationAuditRunRows()) {
    const summary = parseAuditSummaryPayload(row.summary);
    if (!summary) {
      continue;
    }
    const station = stationMap.get(row.station_key) || findStationByAuditUrl(siteData, summary.auditedBaseUrl);
    const displayStationKey = station?.key || row.station_key;
    history.push({
      ...summary,
      stationKey: displayStationKey,
      stationLabel: station?.label || row.station_key,
      stationUrl: station?.url || summary.auditedBaseUrl,
      runId: row.run_id,
      reportUrl: `/api/audit-report?station=${encodeURIComponent(row.station_key)}&model=${encodeURIComponent(row.model)}&run=${encodeURIComponent(row.run_id)}`,
    });
  }

  history.sort((a, b) => auditSortTime(b.executedAt) - auditSortTime(a.executedAt));
  return history;
}

export async function getAuditHistory(siteData: SiteData): Promise<StationAuditHistoryItem[]> {
  if (postgresAuditHistoryEnabled()) {
    try {
      return await readPostgresAuditHistory(siteData);
    } catch (error) {
      if (!allowFileFallback()) {
        throw error;
      }
    }
  }
  return readFileAuditHistory(siteData);
}
