"use client";

import Link from "next/link";
import { ArrowDownAZ, ArrowUpAZ, ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, ExternalLink, FileText, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { localizeAuditText } from "@/lib/audit-localization";
import { formatAuditVerdict, formatDateTime } from "@/lib/format";
import type {
  AuditHistorySortDirection,
  AuditHistorySortKey,
  AuditHistoryTimeRange,
  AuditVerdict,
  StationAuditHistoryItem,
} from "@/lib/types";

type SelectOption<T extends string> = {
  label: string;
  value: T;
};

const TIME_RANGE_OPTIONS: Array<SelectOption<AuditHistoryTimeRange>> = [
  { label: "全部时间", value: "all" },
  { label: "最近 24 小时", value: "24h" },
  { label: "最近 7 天", value: "7d" },
  { label: "最近 30 天", value: "30d" },
  { label: "最近 90 天", value: "90d" },
];

const VERDICT_OPTIONS: Array<SelectOption<"all" | AuditVerdict>> = [
  { label: "全部风险", value: "all" },
  { label: "高风险", value: "high" },
  { label: "中风险", value: "medium" },
  { label: "低风险", value: "low" },
  { label: "结果未定", value: "inconclusive" },
];

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;

const SORT_LABELS: Record<AuditHistorySortKey, string> = {
  executedAt: "审计时间",
  station: "站点",
  model: "模型",
  verdict: "安全程度",
};

const VERDICT_ORDER: Record<AuditVerdict, number> = {
  high: 3,
  medium: 2,
  low: 1,
  inconclusive: 0,
};

function verdictClass(verdict: AuditVerdict) {
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

function timeRangeCutoff(range: AuditHistoryTimeRange) {
  const now = Date.now();
  if (range === "24h") {
    return now - 24 * 60 * 60 * 1000;
  }
  if (range === "7d") {
    return now - 7 * 24 * 60 * 60 * 1000;
  }
  if (range === "30d") {
    return now - 30 * 24 * 60 * 60 * 1000;
  }
  if (range === "90d") {
    return now - 90 * 24 * 60 * 60 * 1000;
  }
  return null;
}

function auditTimestamp(item: StationAuditHistoryItem) {
  const timestamp = Date.parse(item.executedAt);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function compareAuditRows(a: StationAuditHistoryItem, b: StationAuditHistoryItem, sortKey: AuditHistorySortKey) {
  if (sortKey === "executedAt") {
    return auditTimestamp(a) - auditTimestamp(b);
  }
  if (sortKey === "station") {
    return a.stationLabel.localeCompare(b.stationLabel, "zh-CN");
  }
  if (sortKey === "model") {
    return a.model.localeCompare(b.model, "zh-CN");
  }
  return VERDICT_ORDER[a.overallVerdict] - VERDICT_ORDER[b.overallVerdict];
}

function SortButton({
  active,
  direction,
  label,
  onClick,
}: {
  active: boolean;
  direction: AuditHistorySortDirection;
  label: string;
  onClick: () => void;
}) {
  const Icon = direction === "asc" ? ArrowUpAZ : ArrowDownAZ;
  return (
    <button type="button" className={active ? "audit-history-sort-button is-active" : "audit-history-sort-button"} onClick={onClick}>
      <span>{label}</span>
      {active ? <Icon size={13} /> : null}
    </button>
  );
}

function PageButton({
  children,
  disabled,
  label,
  onClick,
}: {
  children: ReactNode;
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className="audit-history-page-button" disabled={disabled} aria-label={label} onClick={onClick}>
      {children}
    </button>
  );
}

function AuditHistoryCard({ item }: { item: StationAuditHistoryItem }) {
  return (
    <article className="mobile-card audit-history-card">
      <div className="mobile-card-header">
        <div className="mobile-card-title-block">
          <Link href={`/stations/${item.stationKey}`} className="station-link mobile-card-title">
            {item.stationLabel}
          </Link>
          <span className="mobile-card-subtitle">{item.auditedBaseUrl}</span>
        </div>
        <span className={`audit-verdict-pill ${verdictClass(item.overallVerdict)}`}>{formatAuditVerdict(item.overallVerdict)}</span>
      </div>
      <div className="mobile-metrics-grid">
        <div className="mobile-metric">
          <span className="mobile-metric-label">模型</span>
          <span className="mobile-metric-value mono">{item.model}</span>
        </div>
        <div className="mobile-metric">
          <span className="mobile-metric-label">时间</span>
          <span className="mobile-metric-value">{formatDateTime(item.executedAt)}</span>
        </div>
      </div>
      <p className="audit-history-summary">{localizeAuditText(item.overallSummary) || "审计报告未给出摘要。"}</p>
      <div className="mobile-card-actions">
        <a href={item.reportUrl} target="_blank" rel="noreferrer" className="tiny-button mobile-card-button">
          原始报告
          <ExternalLink size={14} />
        </a>
      </div>
    </article>
  );
}

export function AuditHistoryTable({ history }: { history: StationAuditHistoryItem[] }) {
  const [stationFilter, setStationFilter] = useState("all");
  const [modelFilter, setModelFilter] = useState("all");
  const [verdictFilter, setVerdictFilter] = useState<"all" | AuditVerdict>("all");
  const [timeRange, setTimeRange] = useState<AuditHistoryTimeRange>("all");
  const [sortKey, setSortKey] = useState<AuditHistorySortKey>("executedAt");
  const [sortDirection, setSortDirection] = useState<AuditHistorySortDirection>("desc");
  const [pageSize, setPageSize] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);

  const stationOptions = useMemo(() => {
    const byKey = new Map(history.map((item) => [item.stationKey, item.stationLabel]));
    return [...byKey.entries()].sort((a, b) => a[1].localeCompare(b[1], "zh-CN"));
  }, [history]);

  const modelOptions = useMemo(() => {
    return [...new Set(history.map((item) => item.model))].sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [history]);

  const visibleRows = useMemo(() => {
    const cutoff = timeRangeCutoff(timeRange);
    const rows = history.filter((item) => {
      if (stationFilter !== "all" && item.stationKey !== stationFilter) {
        return false;
      }
      if (modelFilter !== "all" && item.model !== modelFilter) {
        return false;
      }
      if (verdictFilter !== "all" && item.overallVerdict !== verdictFilter) {
        return false;
      }
      if (cutoff !== null && auditTimestamp(item) < cutoff) {
        return false;
      }
      return true;
    });
    rows.sort((a, b) => {
      const result = compareAuditRows(a, b, sortKey);
      if (result !== 0) {
        return sortDirection === "asc" ? result : -result;
      }
      return auditTimestamp(b) - auditTimestamp(a);
    });
    return rows;
  }, [history, modelFilter, sortDirection, sortKey, stationFilter, timeRange, verdictFilter]);

  useEffect(() => {
    setCurrentPage(1);
  }, [history, modelFilter, pageSize, sortDirection, sortKey, stationFilter, timeRange, verdictFilter]);

  const pageCount = Math.max(1, Math.ceil(visibleRows.length / pageSize));
  const safeCurrentPage = Math.min(currentPage, pageCount);
  const pageStartIndex = (safeCurrentPage - 1) * pageSize;
  const pageEndIndex = Math.min(pageStartIndex + pageSize, visibleRows.length);
  const paginatedRows = visibleRows.slice(pageStartIndex, pageEndIndex);
  const displayStart = visibleRows.length > 0 ? pageStartIndex + 1 : 0;
  const displayEnd = visibleRows.length > 0 ? pageEndIndex : 0;

  function toggleSort(nextSortKey: AuditHistorySortKey) {
    if (nextSortKey === sortKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(nextSortKey);
    setSortDirection(nextSortKey === "executedAt" || nextSortKey === "verdict" ? "desc" : "asc");
  }

  function updatePageSize(value: string) {
    setPageSize(Number(value));
    setCurrentPage(1);
  }

  return (
    <section className="section audit-history-section">
      <div className="section-head audit-history-head">
        <div>
          <h2 className="section-title">审计历史</h2>
          <p className="section-desc">展示本地归档的全部安全审计记录，可按站点、模型、风险等级和时间区间筛选。</p>
        </div>
        <div className="controls audit-history-controls">
          <label className="control-group">
            <span className="control-label">站点</span>
            <select aria-label="站点" className="toolbar-select" value={stationFilter} onChange={(event) => setStationFilter(event.target.value)}>
              <option value="all">全部站点</option>
              {stationOptions.map(([stationKey, label]) => (
                <option key={stationKey} value={stationKey}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group">
            <span className="control-label">模型</span>
            <select aria-label="模型" className="toolbar-select" value={modelFilter} onChange={(event) => setModelFilter(event.target.value)}>
              <option value="all">全部模型</option>
              {modelOptions.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group">
            <span className="control-label">安全程度</span>
            <select aria-label="安全程度" className="toolbar-select" value={verdictFilter} onChange={(event) => setVerdictFilter(event.target.value as "all" | AuditVerdict)}>
              {VERDICT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group">
            <span className="control-label">时间</span>
            <select aria-label="时间" className="toolbar-select" value={timeRange} onChange={(event) => setTimeRange(event.target.value as AuditHistoryTimeRange)}>
              {TIME_RANGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="section-body">
        <div className="audit-history-sortbar" aria-label="排序">
          {(Object.keys(SORT_LABELS) as AuditHistorySortKey[]).map((key) => (
            <SortButton key={key} active={sortKey === key} direction={sortDirection} label={SORT_LABELS[key]} onClick={() => toggleSort(key)} />
          ))}
        </div>

        {visibleRows.length > 0 ? (
          <>
            <div className="desktop-table">
              <div className="table-wrap">
                <table className="data-table audit-history-table">
                  <thead>
                    <tr>
                      <th>审计时间</th>
                      <th>站点</th>
                      <th>模型</th>
                      <th>安全程度</th>
                      <th>审计地址</th>
                      <th>摘要</th>
                      <th className="col-action">报告</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedRows.map((item) => (
                      <tr key={`${item.stationKey}-${item.model}-${item.runId}`}>
                        <td className="mono audit-history-time">{formatDateTime(item.executedAt)}</td>
                        <td>
                          <Link href={`/stations/${item.stationKey}`} className="station-link">
                            {item.stationLabel}
                          </Link>
                        </td>
                        <td className="mono">{item.model}</td>
                        <td>
                          <span className={`audit-verdict-pill ${verdictClass(item.overallVerdict)}`}>{formatAuditVerdict(item.overallVerdict)}</span>
                        </td>
                        <td className="table-url-cell audit-history-url">{item.auditedBaseUrl || "-"}</td>
                        <td className="audit-history-summary-cell">{localizeAuditText(item.overallSummary) || "审计报告未给出摘要。"}</td>
                        <td className="table-action-cell">
                          <a href={item.reportUrl} target="_blank" rel="noreferrer" className="tiny-button">
                            <FileText size={14} />
                            报告
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mobile-card-list audit-history-mobile-list">
              {paginatedRows.map((item) => (
                <AuditHistoryCard key={`${item.stationKey}-${item.model}-${item.runId}`} item={item} />
              ))}
            </div>
            <div className="audit-history-pagination" aria-label="审计历史分页">
              <div className="audit-history-page-meta">
                <span>
                  第 {safeCurrentPage} / {pageCount} 页
                </span>
                <span>
                  显示 {displayStart}-{displayEnd} / {visibleRows.length} 条
                </span>
              </div>
              <div className="audit-history-page-controls">
                <PageButton label="第一页" disabled={safeCurrentPage <= 1} onClick={() => setCurrentPage(1)}>
                  <ChevronFirst size={15} />
                </PageButton>
                <PageButton label="上一页" disabled={safeCurrentPage <= 1} onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}>
                  <ChevronLeft size={15} />
                </PageButton>
                <PageButton label="下一页" disabled={safeCurrentPage >= pageCount} onClick={() => setCurrentPage((page) => Math.min(pageCount, page + 1))}>
                  <ChevronRight size={15} />
                </PageButton>
                <PageButton label="最后一页" disabled={safeCurrentPage >= pageCount} onClick={() => setCurrentPage(pageCount)}>
                  <ChevronLast size={15} />
                </PageButton>
              </div>
              <label className="audit-history-page-size">
                <span>每页显示</span>
                <select aria-label="每页显示" className="toolbar-select" value={pageSize} onChange={(event) => updatePageSize(event.target.value)}>
                  {PAGE_SIZE_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option} 条
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </>
        ) : (
          <div className="audit-history-empty">
            <ShieldAlert size={18} />
            <span>当前筛选条件下没有审计记录。</span>
          </div>
        )}

        <div className="footer-note">
          共 {history.length} 条历史记录，当前筛选 {visibleRows.length} 条 · 排序：{SORT_LABELS[sortKey]}（{sortDirection === "asc" ? "升序" : "降序"}）
        </div>
      </div>
    </section>
  );
}
