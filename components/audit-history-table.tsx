"use client";

import Link from "next/link";
import type { Route } from "next";
import { ArrowDownAZ, ArrowUpAZ, ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, ExternalLink, FileText, ShieldAlert } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTransition, type ReactNode } from "react";

import { localizeAuditText } from "@/lib/audit-localization";
import { formatAuditVerdict, formatDateTime } from "@/lib/format";
import type {
  AuditHistoryFilters,
  AuditHistoryPage,
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
  score: "综合分",
};

const DEFAULT_FILTERS: AuditHistoryFilters = {
  station: "all",
  model: "all",
  verdict: "all",
  timeRange: "all",
  sort: "executedAt",
  direction: "desc",
  page: 1,
  pageSize: 10,
};

const SUMMARY_DIMENSIONS = [
  { key: "protocol", label: "协议", field: "protocolVerdict" },
  { key: "capability", label: "能力", field: "capabilityVerdict" },
  { key: "authenticity", label: "真伪", field: "authenticityVerdict" },
  { key: "long-context", label: "长上下文", field: "longContextVerdict" },
] as const satisfies ReadonlyArray<{ key: string; label: string; field: keyof StationAuditHistoryItem }>;

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

function summaryText(item: StationAuditHistoryItem) {
  return item.auditVerdictReason || localizeAuditText(item.overallSummary) || "审计报告未给出摘要。";
}

function dimensionStatusLabel(value: string) {
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
  if (value === "skip") {
    return "跳过";
  }
  if (value === "error") {
    return "异常";
  }
  return value;
}

function dimensionTone(value: string) {
  if (value === "fail" || value === "error") {
    return "fail";
  }
  if (value === "warn") {
    return "warn";
  }
  if (value === "pass") {
    return "pass";
  }
  if (value === "not_run" || value === "skip") {
    return "skip";
  }
  return "neutral";
}

function summaryDimensions(item: StationAuditHistoryItem) {
  return SUMMARY_DIMENSIONS.flatMap((dimension) => {
    const value = String(item[dimension.field] || "").trim();
    if (!value || value === "unknown") {
      return [];
    }
    return [
      {
        key: dimension.key,
        label: dimension.label,
        value,
      },
    ];
  });
}

function AuditHistorySummaryBlock({ item }: { item: StationAuditHistoryItem }) {
  const criticalCount = item.criticalFindings?.length ?? 0;
  const dimensions = summaryDimensions(item);
  return (
    <div className="audit-history-summary-block">
      <p className="audit-history-summary-main">{summaryText(item)}</p>
      {dimensions.length > 0 ? (
        <div className="audit-history-summary-chips" aria-label="检测维度摘要">
          {dimensions.map((dimension) => (
            <span className={`audit-history-summary-chip audit-history-summary-chip-${dimensionTone(dimension.value)}`} key={dimension.key}>
              <span>{dimension.label}</span>
              <strong>{dimensionStatusLabel(dimension.value)}</strong>
            </span>
          ))}
        </div>
      ) : null}
      {criticalCount > 0 ? <p className="audit-history-critical">Critical findings：{criticalCount} 个</p> : null}
    </div>
  );
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
          <Link href={`/stations/${item.stationKey}`} prefetch={false} className="station-link mobile-card-title">
            {item.stationLabel}
          </Link>
          <span className="mobile-card-subtitle">{item.auditedBaseUrl}</span>
        </div>
        <span className={`audit-verdict-pill ${verdictClass(item.overallVerdict)}`}>{formatAuditVerdict(item.overallVerdict)}</span>
      </div>
      <div className="mobile-metrics-grid">
        <div className="mobile-metric">
          <span className="mobile-metric-label">综合分</span>
          <span className="mobile-metric-value mono">{typeof item.auditScore === "number" ? `${item.auditScore}/100` : "-"}</span>
        </div>
        <div className="mobile-metric">
          <span className="mobile-metric-label">模型</span>
          <span className="mobile-metric-value mono">{item.model}</span>
        </div>
        <div className="mobile-metric">
          <span className="mobile-metric-label">时间</span>
          <span className="mobile-metric-value">{formatDateTime(item.executedAt)}</span>
        </div>
      </div>
      <AuditHistorySummaryBlock item={item} />
      <div className="mobile-card-actions">
        <a href={item.reportUrl} target="_blank" rel="noreferrer" className="tiny-button mobile-card-button">
          原始报告
          <ExternalLink size={14} />
        </a>
      </div>
    </article>
  );
}

export function AuditHistoryTable({ historyPage }: { historyPage: AuditHistoryPage }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();
  const { filters } = historyPage;
  const paginatedRows = historyPage.items;
  const pageStartIndex = (historyPage.page - 1) * historyPage.pageSize;
  const displayStart = historyPage.total > 0 ? pageStartIndex + 1 : 0;
  const displayEnd = historyPage.total > 0 ? pageStartIndex + paginatedRows.length : 0;

  function updateQuery(patch: Partial<AuditHistoryFilters>) {
    const next: AuditHistoryFilters = {
      ...filters,
      ...patch,
      page: patch.page ?? 1,
    };
    const params = new URLSearchParams(searchParams.toString());
    const setOrDelete = (key: keyof AuditHistoryFilters, value: string | number) => {
      if (String(value) === String(DEFAULT_FILTERS[key])) {
        params.delete(key);
        return;
      }
      params.set(key, String(value));
    };
    setOrDelete("station", next.station);
    setOrDelete("model", next.model);
    setOrDelete("verdict", next.verdict);
    setOrDelete("timeRange", next.timeRange);
    setOrDelete("sort", next.sort);
    setOrDelete("direction", next.direction);
    setOrDelete("page", next.page);
    setOrDelete("pageSize", next.pageSize);

    const query = params.toString();
    startTransition(() => {
      const nextUrl = query ? `${pathname}?${query}` : pathname;
      router.replace(nextUrl as Route, { scroll: false });
    });
  }

  function defaultDirection(sortKey: AuditHistorySortKey): AuditHistorySortDirection {
    return sortKey === "executedAt" || sortKey === "verdict" || sortKey === "score" ? "desc" : "asc";
  }

  function toggleSort(nextSortKey: AuditHistorySortKey) {
    if (nextSortKey === filters.sort) {
      updateQuery({ direction: filters.direction === "asc" ? "desc" : "asc" });
      return;
    }
    updateQuery({ sort: nextSortKey, direction: defaultDirection(nextSortKey) });
  }

  return (
    <section className="section audit-history-section">
      <div className="section-head audit-history-head">
        <div>
          <h2 className="section-title">审计历史</h2>
          <p className="section-desc">按当前筛选条件从服务端分页读取审计记录，筛选、排序和页码会同步到 URL。</p>
        </div>
        <div className="controls audit-history-controls">
          <label className="control-group">
            <span className="control-label">站点</span>
            <select aria-label="站点" className="toolbar-select" value={filters.station} onChange={(event) => updateQuery({ station: event.target.value })}>
              <option value="all">全部站点</option>
              {historyPage.options.stations.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group">
            <span className="control-label">模型</span>
            <select aria-label="模型" className="toolbar-select" value={filters.model} onChange={(event) => updateQuery({ model: event.target.value })}>
              <option value="all">全部模型</option>
              {historyPage.options.models.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group">
            <span className="control-label">安全程度</span>
            <select aria-label="安全程度" className="toolbar-select" value={filters.verdict} onChange={(event) => updateQuery({ verdict: event.target.value as "all" | AuditVerdict })}>
              {VERDICT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="control-group">
            <span className="control-label">时间</span>
            <select aria-label="时间" className="toolbar-select" value={filters.timeRange} onChange={(event) => updateQuery({ timeRange: event.target.value as AuditHistoryTimeRange })}>
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
            <SortButton key={key} active={filters.sort === key} direction={filters.direction} label={SORT_LABELS[key]} onClick={() => toggleSort(key)} />
          ))}
          {isPending ? <span className="footer-note">正在加载...</span> : null}
        </div>

        {paginatedRows.length > 0 ? (
          <>
            <div className="desktop-table">
              <div className="table-wrap">
                <table className="data-table audit-history-table">
                  <thead>
                    <tr>
                      <th>审计时间</th>
                      <th>站点</th>
                      <th>模型</th>
                      <th>综合分</th>
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
                          <Link href={`/stations/${item.stationKey}`} prefetch={false} className="station-link">
                            {item.stationLabel}
                          </Link>
                        </td>
                        <td className="mono">{item.model}</td>
                        <td className="mono audit-history-score">{typeof item.auditScore === "number" ? `${item.auditScore}/100` : "-"}</td>
                        <td>
                          <span className={`audit-verdict-pill ${verdictClass(item.overallVerdict)}`}>{formatAuditVerdict(item.overallVerdict)}</span>
                          {item.criticalFindings?.length ? <span className="audit-history-critical-inline">C{item.criticalFindings.length}</span> : null}
                        </td>
                        <td className="table-url-cell audit-history-url">{item.auditedBaseUrl || "-"}</td>
                        <td className="audit-history-summary-cell">
                          <AuditHistorySummaryBlock item={item} />
                        </td>
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
                  第 {historyPage.page} / {historyPage.pageCount} 页
                </span>
                <span>
                  显示 {displayStart}-{displayEnd} / {historyPage.total} 条
                </span>
              </div>
              <div className="audit-history-page-controls">
                <PageButton label="第一页" disabled={historyPage.page <= 1 || isPending} onClick={() => updateQuery({ page: 1 })}>
                  <ChevronFirst size={15} />
                </PageButton>
                <PageButton label="上一页" disabled={historyPage.page <= 1 || isPending} onClick={() => updateQuery({ page: Math.max(1, historyPage.page - 1) })}>
                  <ChevronLeft size={15} />
                </PageButton>
                <PageButton label="下一页" disabled={historyPage.page >= historyPage.pageCount || isPending} onClick={() => updateQuery({ page: Math.min(historyPage.pageCount, historyPage.page + 1) })}>
                  <ChevronRight size={15} />
                </PageButton>
                <PageButton label="最后一页" disabled={historyPage.page >= historyPage.pageCount || isPending} onClick={() => updateQuery({ page: historyPage.pageCount })}>
                  <ChevronLast size={15} />
                </PageButton>
              </div>
              <label className="audit-history-page-size">
                <span>每页显示</span>
                <select aria-label="每页显示" className="toolbar-select" value={historyPage.pageSize} onChange={(event) => updateQuery({ pageSize: Number(event.target.value) })}>
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
          当前筛选共 {historyPage.total} 条 · 排序：{SORT_LABELS[filters.sort]}（{filters.direction === "asc" ? "升序" : "降序"}）· 首屏只加载当前页
        </div>
      </div>
    </section>
  );
}
