import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import {
  hasDatabaseUrl,
  readStationAuditRunFilterValues,
  readStationAuditRunPage,
  readStationAuditRunRows,
  type StationAuditRunRow,
} from "./postgres";
import { AUDIT_RUNS_ROOT, resolveLogicalDataPath } from "./runtime-paths";
import type {
  AuditHistoryFilterOption,
  AuditHistoryFilterOptions,
  AuditHistoryFilters,
  AuditHistoryPage,
  AuditHistorySortDirection,
  AuditHistorySortKey,
  AuditHistoryTimeRange,
  AuditVerdict,
  SiteData,
  StationAuditDetectorResult,
  StationAuditHistoryItem,
  StationAuditSummary,
} from "./types";

const AUDIT_SEGMENT_PATTERN = /^[A-Za-z0-9._-]+$/;
const VALID_VERDICTS = new Set<AuditVerdict>(["low", "medium", "high", "inconclusive"]);
const VALID_HISTORY_VERDICTS = new Set<"all" | AuditVerdict>(["all", "low", "medium", "high", "inconclusive"]);
const VALID_TIME_RANGES = new Set<AuditHistoryTimeRange>(["all", "24h", "7d", "30d", "90d"]);
const VALID_SORT_KEYS = new Set<AuditHistorySortKey>(["executedAt", "station", "model", "verdict", "score"]);
const VALID_SORT_DIRECTIONS = new Set<AuditHistorySortDirection>(["asc", "desc"]);
export const AUDIT_HISTORY_PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const DEFAULT_AUDIT_HISTORY_PAGE_SIZE = 10;
const DEFAULT_AUDIT_HISTORY_FILTERS: AuditHistoryFilters = {
  station: "all",
  model: "all",
  verdict: "all",
  timeRange: "all",
  sort: "executedAt",
  direction: "desc",
  page: 1,
  pageSize: DEFAULT_AUDIT_HISTORY_PAGE_SIZE,
};

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

function stringList(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function normalizeDetectorResult(value: unknown): StationAuditDetectorResult | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const item = value as Record<string, unknown>;
  const key = String(item.key || "").trim();
  const label = String(item.label || "").trim();
  const category = String(item.category || "").trim();
  const status = String(item.status || "").trim();
  const summary = String(item.summary || "").trim();
  if (!key || !label || !category || !status) {
    return null;
  }
  const output: StationAuditDetectorResult = {
    key,
    label,
    category,
    status,
    severity: String(item.severity || "").trim(),
    summary,
  };
  if (typeof item.score === "number" && Number.isFinite(item.score)) {
    output.score = item.score;
  }
  if (typeof item.weight === "number" && Number.isFinite(item.weight)) {
    output.weight = item.weight;
  }
  const evidence = stringList(item.evidence);
  if (evidence.length > 0) {
    output.evidence = evidence;
  }
  return output;
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
  if (typeof item.auditScore === "number" && Number.isFinite(item.auditScore)) {
    summary.auditScore = Math.max(0, Math.min(100, Math.round(item.auditScore)));
  }
  for (const [sourceKey, targetKey] of [
    ["auditVerdictReason", "auditVerdictReason"],
    ["capabilityVerdict", "capabilityVerdict"],
    ["protocolVerdict", "protocolVerdict"],
    ["authenticityVerdict", "authenticityVerdict"],
    ["longContextVerdict", "longContextVerdict"],
    ["runMode", "runMode"],
    ["costNotice", "costNotice"],
  ] as const) {
    const value = String(item[sourceKey] || "").trim();
    if (value) {
      summary[targetKey] = value;
    }
  }
  const detectorResults = Array.isArray(item.detectorResults)
    ? item.detectorResults.flatMap((detector) => {
        const normalized = normalizeDetectorResult(detector);
        return normalized ? [normalized] : [];
      })
    : [];
  if (detectorResults.length > 0) {
    summary.detectorResults = detectorResults;
  }
  const criticalFindings = stringList(item.criticalFindings);
  if (criticalFindings.length > 0) {
    summary.criticalFindings = criticalFindings;
  }
  return summary;
}

function auditSortTime(value: string) {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function auditTimeRangeCutoff(range: AuditHistoryTimeRange) {
  const now = Date.now();
  if (range === "24h") {
    return new Date(now - 24 * 60 * 60 * 1000).toISOString();
  }
  if (range === "7d") {
    return new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString();
  }
  if (range === "30d") {
    return new Date(now - 30 * 24 * 60 * 60 * 1000).toISOString();
  }
  if (range === "90d") {
    return new Date(now - 90 * 24 * 60 * 60 * 1000).toISOString();
  }
  return "";
}

function firstSearchValue(input: URLSearchParams | Record<string, string | string[] | undefined> | undefined, key: string) {
  if (!input) {
    return "";
  }
  if (input instanceof URLSearchParams) {
    return input.get(key)?.trim() || "";
  }
  const value = input[key];
  if (Array.isArray(value)) {
    return value[0]?.trim() || "";
  }
  return value?.trim() || "";
}

function positiveInt(value: string, fallback: number) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function parseAuditHistorySearchParams(input?: URLSearchParams | Record<string, string | string[] | undefined>): AuditHistoryFilters {
  const station = firstSearchValue(input, "station") || DEFAULT_AUDIT_HISTORY_FILTERS.station;
  const model = firstSearchValue(input, "model") || DEFAULT_AUDIT_HISTORY_FILTERS.model;
  const verdictValue = firstSearchValue(input, "verdict") as "all" | AuditVerdict;
  const timeRangeValue = firstSearchValue(input, "timeRange") as AuditHistoryTimeRange;
  const sortValue = firstSearchValue(input, "sort") as AuditHistorySortKey;
  const directionValue = firstSearchValue(input, "direction") as AuditHistorySortDirection;
  const requestedPageSize = positiveInt(firstSearchValue(input, "pageSize"), DEFAULT_AUDIT_HISTORY_FILTERS.pageSize);
  const pageSize = AUDIT_HISTORY_PAGE_SIZE_OPTIONS.includes(requestedPageSize as (typeof AUDIT_HISTORY_PAGE_SIZE_OPTIONS)[number])
    ? requestedPageSize
    : DEFAULT_AUDIT_HISTORY_FILTERS.pageSize;

  return {
    station,
    model,
    verdict: VALID_HISTORY_VERDICTS.has(verdictValue) ? verdictValue : DEFAULT_AUDIT_HISTORY_FILTERS.verdict,
    timeRange: VALID_TIME_RANGES.has(timeRangeValue) ? timeRangeValue : DEFAULT_AUDIT_HISTORY_FILTERS.timeRange,
    sort: VALID_SORT_KEYS.has(sortValue) ? sortValue : DEFAULT_AUDIT_HISTORY_FILTERS.sort,
    direction: VALID_SORT_DIRECTIONS.has(directionValue) ? directionValue : DEFAULT_AUDIT_HISTORY_FILTERS.direction,
    page: positiveInt(firstSearchValue(input, "page"), DEFAULT_AUDIT_HISTORY_FILTERS.page),
    pageSize,
  };
}

function auditHistoryPageCount(total: number, pageSize: number) {
  return Math.max(1, Math.ceil(total / pageSize));
}

function stationOption(siteData: SiteData, stationKey: string): AuditHistoryFilterOption {
  const station = siteData.stations.find((item) => item.key === stationKey);
  return {
    value: stationKey,
    label: station?.label || stationKey,
  };
}

function auditHistoryOptions(siteData: SiteData, rows: StationAuditHistoryItem[]): AuditHistoryFilterOptions {
  const stationKeys = [...new Set(rows.map((item) => item.stationKey))].sort((a, b) => stationOption(siteData, a).label.localeCompare(stationOption(siteData, b).label, "zh-CN"));
  const models = [...new Set(rows.map((item) => item.model))].sort((a, b) => a.localeCompare(b, "zh-CN"));
  return {
    stations: stationKeys.map((key) => stationOption(siteData, key)),
    models: models.map((model) => ({ value: model, label: model })),
  };
}

function auditHistoryOptionsFromValues(siteData: SiteData, stationKeys: string[], models: string[]): AuditHistoryFilterOptions {
  const stations = [...new Set(stationKeys)]
    .sort((a, b) => stationOption(siteData, a).label.localeCompare(stationOption(siteData, b).label, "zh-CN"))
    .map((key) => stationOption(siteData, key));
  return {
    stations,
    models: [...new Set(models)].sort((a, b) => a.localeCompare(b, "zh-CN")).map((model) => ({ value: model, label: model })),
  };
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

function stationMap(siteData: SiteData) {
  return new Map(siteData.stations.map((station) => [station.key, station]));
}

function auditHistoryItemFromRow(
  siteData: SiteData,
  row: StationAuditRunRow,
  stationsByKey = stationMap(siteData),
): StationAuditHistoryItem | null {
  const summary = parseAuditSummaryPayload(row.summary);
  if (!summary) {
    return null;
  }
  const station = stationsByKey.get(row.station_key) || findStationByAuditUrl(siteData, summary.auditedBaseUrl);
  return {
    ...summary,
    stationKey: station?.key || row.station_key,
    stationLabel: station?.label || row.station_key,
    stationUrl: station?.url || summary.auditedBaseUrl,
    runId: row.run_id,
    reportUrl: `/api/audit-report?station=${encodeURIComponent(row.station_key)}&model=${encodeURIComponent(row.model)}&run=${encodeURIComponent(row.run_id)}`,
  };
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
  const history: StationAuditHistoryItem[] = [];
  const stationsByKey = stationMap(siteData);

  for (const row of await readStationAuditRunRows()) {
    const item = auditHistoryItemFromRow(siteData, row, stationsByKey);
    if (item) {
      history.push(item);
    }
  }

  history.sort((a, b) => auditSortTime(b.executedAt) - auditSortTime(a.executedAt));
  return history;
}

function auditHistoryItemMatchesFilters(item: StationAuditHistoryItem, filters: AuditHistoryFilters) {
  if (filters.station !== "all" && item.stationKey !== filters.station) {
    return false;
  }
  if (filters.model !== "all" && item.model !== filters.model) {
    return false;
  }
  if (filters.verdict !== "all" && item.overallVerdict !== filters.verdict) {
    return false;
  }
  const cutoff = auditTimeRangeCutoff(filters.timeRange);
  if (cutoff && auditSortTime(item.executedAt) < auditSortTime(cutoff)) {
    return false;
  }
  return true;
}

const AUDIT_VERDICT_ORDER: Record<AuditVerdict, number> = {
  high: 3,
  medium: 2,
  low: 1,
  inconclusive: 0,
};

function auditHistorySortValue(item: StationAuditHistoryItem, sort: AuditHistorySortKey) {
  if (sort === "executedAt") {
    return auditSortTime(item.executedAt);
  }
  if (sort === "station") {
    return item.stationLabel;
  }
  if (sort === "model") {
    return item.model;
  }
  if (sort === "score") {
    return item.auditScore ?? -1;
  }
  return AUDIT_VERDICT_ORDER[item.overallVerdict];
}

function compareAuditHistoryItems(left: StationAuditHistoryItem, right: StationAuditHistoryItem, filters: AuditHistoryFilters) {
  const leftValue = auditHistorySortValue(left, filters.sort);
  const rightValue = auditHistorySortValue(right, filters.sort);
  let result = 0;
  if (typeof leftValue === "string" || typeof rightValue === "string") {
    result = String(leftValue).localeCompare(String(rightValue), "zh-CN");
  } else {
    result = Number(leftValue) - Number(rightValue);
  }
  if (result !== 0) {
    return filters.direction === "asc" ? result : -result;
  }
  return auditSortTime(right.executedAt) - auditSortTime(left.executedAt);
}

function paginateAuditHistoryItems(siteData: SiteData, rows: StationAuditHistoryItem[], filters: AuditHistoryFilters): AuditHistoryPage {
  const options = auditHistoryOptions(siteData, rows);
  const filtered = rows.filter((item) => auditHistoryItemMatchesFilters(item, filters)).sort((a, b) => compareAuditHistoryItems(a, b, filters));
  const total = filtered.length;
  const pageCount = auditHistoryPageCount(total, filters.pageSize);
  const page = Math.min(filters.page, pageCount);
  const start = (page - 1) * filters.pageSize;
  return {
    items: filtered.slice(start, start + filters.pageSize),
    total,
    page,
    pageSize: filters.pageSize,
    pageCount,
    filters: { ...filters, page },
    options,
  };
}

async function readPostgresAuditHistoryPage(siteData: SiteData, filters: AuditHistoryFilters): Promise<AuditHistoryPage> {
  const executedAfter = auditTimeRangeCutoff(filters.timeRange);
  const query = {
    station: filters.station === "all" ? undefined : filters.station,
    model: filters.model === "all" ? undefined : filters.model,
    verdict: filters.verdict === "all" ? undefined : filters.verdict,
    executedAfter: executedAfter || undefined,
    sort: filters.sort,
    direction: filters.direction,
    limit: filters.pageSize,
    offset: (filters.page - 1) * filters.pageSize,
  };
  let result = await readStationAuditRunPage(query);
  let pageCount = auditHistoryPageCount(result.total, filters.pageSize);
  let page = Math.min(filters.page, pageCount);
  if (page !== filters.page) {
    result = await readStationAuditRunPage({
      ...query,
      offset: (page - 1) * filters.pageSize,
    });
    pageCount = auditHistoryPageCount(result.total, filters.pageSize);
    page = Math.min(page, pageCount);
  }
  const values = await readStationAuditRunFilterValues();
  const stationsByKey = stationMap(siteData);
  return {
    items: result.rows.flatMap((row) => {
      const item = auditHistoryItemFromRow(siteData, row, stationsByKey);
      return item ? [item] : [];
    }),
    total: result.total,
    page,
    pageSize: filters.pageSize,
    pageCount,
    filters: { ...filters, page },
    options: auditHistoryOptionsFromValues(siteData, values.stationKeys, values.models),
  };
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

export async function getAuditHistoryPage(siteData: SiteData, filters: AuditHistoryFilters): Promise<AuditHistoryPage> {
  if (postgresAuditHistoryEnabled()) {
    try {
      return await readPostgresAuditHistoryPage(siteData, filters);
    } catch (error) {
      if (!allowFileFallback()) {
        throw error;
      }
    }
  }
  return paginateAuditHistoryItems(siteData, await readFileAuditHistory(siteData), filters);
}
