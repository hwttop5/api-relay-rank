"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { ChevronDown, ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, ExternalLink, Medal } from "lucide-react";

import { formatCompactCount, formatMultiplier, formatPercent, formatScore, formatSeconds } from "@/lib/format";
import type { PageViewStats, RankingDisplayRow, RankingPageData, RankingStationRecord, ShellData, SortMode, StationType, TimeWindow } from "@/lib/types";
import { AppShell, StatusChip } from "@/components/app-shell";
import { formatReviewSummary } from "@/lib/user-feedback";

const TIME_WINDOW_OPTIONS: Array<{ value: TimeWindow; label: string }> = [
  { value: "all_hours", label: "全部时段" },
  { value: "work_hours", label: "工作时段" },
  { value: "off_hours", label: "非工作时段" }
];

const SORT_OPTIONS: Array<{ value: SortMode; label: string }> = [
  { value: "composite", label: "综合排序" },
  { value: "correct_rate", label: "正确率优先" },
  { value: "avg_seconds", label: "响应时间优先" },
  { value: "effective_multiplier", label: "采用倍率优先" },
  { value: "review_rating", label: "用户评分优先" }
];

const TYPE_OPTIONS = [
  { key: "all", label: "全部类型" },
  { key: "subscription", label: "包月型" },
  { key: "non_subscription", label: "非包月型" },
  { key: "mixed", label: "混合型" },
  { key: "charity", label: "公益站" }
] as const;

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
const PRIORITY_RANKING_MIN_REQUESTS = 10;
const DISPLAY_REDACTED_URLS: Record<string, string> = {
  "https://ttop5.gettoken.dev": "https://xxx.gettoken.dev",
};

type TypeFilter = (typeof TYPE_OPTIONS)[number]["key"];
type StationRecord = RankingStationRecord;

function compareByMode(rowA: RankingDisplayRow, rowB: RankingDisplayRow, mode: SortMode): number {
  const samplePriority = Number(rowA.requests < PRIORITY_RANKING_MIN_REQUESTS) - Number(rowB.requests < PRIORITY_RANKING_MIN_REQUESTS);
  if (samplePriority !== 0) {
    return samplePriority;
  }
  if (mode === "correct_rate") {
    return rowB.correctRate - rowA.correctRate || rowA.avgSeconds - rowB.avgSeconds || rowA.effectiveMultiplier - rowB.effectiveMultiplier || rowA.rank - rowB.rank;
  }
  if (mode === "avg_seconds") {
    return rowA.avgSeconds - rowB.avgSeconds || rowB.correctRate - rowA.correctRate || rowA.effectiveMultiplier - rowB.effectiveMultiplier || rowA.rank - rowB.rank;
  }
  if (mode === "effective_multiplier") {
    return rowA.effectiveMultiplier - rowB.effectiveMultiplier || rowB.totalScore - rowA.totalScore || rowA.rank - rowB.rank;
  }
  if (mode === "review_rating") {
    const ratingPriority = Number(rowB.reviewCount > 0 && rowB.reviewAverageRating !== null) - Number(rowA.reviewCount > 0 && rowA.reviewAverageRating !== null);
    if (ratingPriority !== 0) {
      return ratingPriority;
    }
    return (
      (rowB.reviewAverageRating ?? -1) - (rowA.reviewAverageRating ?? -1) ||
      rowB.reviewCount - rowA.reviewCount ||
      rowB.totalScore - rowA.totalScore ||
      rowA.rank - rowB.rank
    );
  }
  return rowB.totalScore - rowA.totalScore || rowA.rank - rowB.rank;
}

function getOfficialUrl(href: string) {
  if (DISPLAY_REDACTED_URLS[href]) {
    return DISPLAY_REDACTED_URLS[href];
  }
  try {
    return new URL(href).origin;
  } catch {
    return href;
  }
}

function StationUrlLink({ href, compact = false }: { href: string; compact?: boolean }) {
  if (!href) {
    return <span className="subtle">未记录</span>;
  }

  const displayHref = DISPLAY_REDACTED_URLS[href] || (compact ? getOfficialUrl(href) : href);

  return (
    <a href={href} target="_blank" rel="noreferrer" className="station-link inline-actions">
      <span>{displayHref}</span>
      <ExternalLink size={14} />
    </a>
  );
}

function getStationTone(stationType: StationType): "default" | "accent" | "blue" | "warn" | "success" {
  if (stationType === "subscription") {
    return "blue";
  }
  if (stationType === "non_subscription") {
    return "warn";
  }
  if (stationType === "mixed") {
    return "accent";
  }
  if (stationType === "charity") {
    return "success";
  }
  return "default";
}

function RankingReviewSummary({
  reviewAverageRating,
  reviewCount,
  stationKey,
}: {
  reviewAverageRating: number | null;
  reviewCount: number;
  stationKey: string;
}) {
  const hasReviewScore = reviewCount > 0 && reviewAverageRating !== null;
  return (
    <Link href={`/stations/${stationKey}#reviews`} prefetch={false} className={hasReviewScore ? "ranking-review-summary" : "ranking-review-summary ranking-review-empty"}>
      {hasReviewScore ? formatReviewSummary({ station: stationKey, averageRating: reviewAverageRating, reviewCount }) : "暂无数据"}
    </Link>
  );
}

function RankMedal({ rank }: { rank: number }) {
  if (rank < 1 || rank > 3) {
    return null;
  }
  const label = rank === 1 ? "金牌" : rank === 2 ? "银牌" : "铜牌";
  const tone = rank === 1 ? "gold" : rank === 2 ? "silver" : "bronze";
  return (
    <span className={`rank-medal rank-medal-${tone}`} aria-label={label} title={label}>
      <Medal size={14} strokeWidth={2.4} aria-hidden="true" />
    </span>
  );
}

function RankingPosition({ fallbackIndex }: { fallbackIndex: number }) {
  const displayRank = fallbackIndex + 1;
  return (
    <div className="ranking-position">
      <span className="ranking-position-number">#{displayRank}</span>
      <RankMedal rank={displayRank} />
    </div>
  );
}

function CharityBadge({ stationType }: { stationType: StationType }) {
  if (stationType !== "charity") {
    return null;
  }
  return (
    <span className="charity-badge">
      <span className="charity-badge-text">公益</span>
    </span>
  );
}

function MobileMetric({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="mobile-metric">
      <div className="mobile-metric-label">{label}</div>
      <div className={mono ? "mobile-metric-value mono" : "mobile-metric-value"}>{value}</div>
    </div>
  );
}

function MobileDetail({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="mobile-detail-row">
      <div className="mobile-detail-label">{label}</div>
      <div className="mobile-detail-value">{value}</div>
    </div>
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
    <button type="button" className="table-page-button" disabled={disabled} aria-label={label} onClick={onClick}>
      {children}
    </button>
  );
}

function TablePagination({
  ariaLabel,
  currentPage,
  displayEnd,
  displayStart,
  onPageChange,
  onPageSizeChange,
  pageCount,
  pageSize,
  totalRows,
}: {
  ariaLabel: string;
  currentPage: number;
  displayEnd: number;
  displayStart: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  pageCount: number;
  pageSize: number;
  totalRows: number;
}) {
  return (
    <div className="table-pagination" aria-label={ariaLabel}>
      <div className="table-page-meta">
        <span>
          第 {currentPage} / {pageCount} 页
        </span>
        <span>
          显示 {displayStart}-{displayEnd} / {totalRows} 条
        </span>
      </div>
      <div className="table-page-controls">
        <PageButton label="第一页" disabled={currentPage <= 1} onClick={() => onPageChange(1)}>
          <ChevronFirst size={15} />
        </PageButton>
        <PageButton label="上一页" disabled={currentPage <= 1} onClick={() => onPageChange(Math.max(1, currentPage - 1))}>
          <ChevronLeft size={15} />
        </PageButton>
        <PageButton label="下一页" disabled={currentPage >= pageCount} onClick={() => onPageChange(Math.min(pageCount, currentPage + 1))}>
          <ChevronRight size={15} />
        </PageButton>
        <PageButton label="最后一页" disabled={currentPage >= pageCount} onClick={() => onPageChange(pageCount)}>
          <ChevronLast size={15} />
        </PageButton>
      </div>
      <label className="table-page-size">
        <span>每页显示</span>
        <select aria-label="每页显示" className="toolbar-select" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
          {PAGE_SIZE_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option} 条
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function getRegistryDisplayValues(station: StationRecord) {
  return station.registryDisplay;
}

function getUnrankedReason(station: RankingStationRecord) {
  return station.unrankedReason;
}

function MobileRankingCard({ row, index, stationMeta }: { row: RankingDisplayRow; index: number; stationMeta?: { platformGuess: string } }) {
  return (
    <article className="mobile-card">
      <div className="mobile-card-header">
        <div className="mobile-card-lead">
          <div className="mobile-card-rank mono">
            <RankingPosition fallbackIndex={index} />
          </div>
          <div className="mobile-card-title-block">
            <div className="station-title-line">
              <Link href={`/stations/${row.station}`} prefetch={false} className="station-link mobile-card-title">
                {row.label}
              </Link>
              <CharityBadge stationType={row.stationType} />
            </div>
            <span className="mobile-card-subtitle">{stationMeta?.platformGuess || "-"}</span>
          </div>
        </div>
        <StatusChip label={row.stationTypeShortLabel} tone={getStationTone(row.stationType)} />
      </div>

      <div className="mobile-metrics-grid">
        <MobileMetric label="总分" value={formatScore(row.totalScore)} mono />
        <MobileMetric label="正确率" value={formatPercent(row.correctRate)} mono />
        <MobileMetric label="平均响应" value={formatSeconds(row.avgSeconds)} mono />
        <MobileMetric label="采用倍率" value={formatMultiplier(row.effectiveMultiplier)} mono />
      </div>

      <details className="mobile-card-details" open>
        <summary className="mobile-card-summary">
          <span>更多信息</span>
          <ChevronDown size={14} />
        </summary>
        <div className="mobile-card-detail-grid">
          <MobileDetail label="官方网址" value={<StationUrlLink href={row.stationUrl} compact />} />
          <MobileDetail label="采用档位" value={row.adoptedTier} />
          <MobileDetail label="用户评分" value={<RankingReviewSummary stationKey={row.station} reviewAverageRating={row.reviewAverageRating} reviewCount={row.reviewCount} />} />
          <MobileDetail label="请求样本" value={<span className="mono">{row.requests}</span>} />
        </div>
      </details>

      <div className="mobile-card-actions">
        <Link href={`/stations/${row.station}`} prefetch={false} className="tiny-button mobile-card-button">
          详情
          <ChevronRight size={14} />
        </Link>
      </div>
    </article>
  );
}

function MobileStationCard({ station }: { station: RankingStationRecord }) {
  const unrankedReason = getUnrankedReason(station);
  const registryDisplay = getRegistryDisplayValues(station);
  const stationExternalUrl = station.stationExternalUrl;

  return (
    <article className="mobile-card">
      <div className="mobile-card-header">
        <div className="mobile-card-lead">
          <div className="mobile-card-title-block">
            <Link href={`/stations/${station.key}`} prefetch={false} className="station-link mobile-card-title">
              {station.label}
            </Link>
            <span className="mobile-card-subtitle">{station.platformGuess || "-"}</span>
          </div>
        </div>
        <StatusChip label={station.stationTypeShortLabel} tone={getStationTone(station.stationType)} />
      </div>

      <div className="mobile-metrics-grid">
        <MobileMetric label="最低倍率" value={registryDisplay.lowestMultiplier} mono />
        <MobileMetric label="全部时段样本" value={registryDisplay.sampleCount} mono />
        <MobileMetric label="公告数量" value={registryDisplay.announcementCount} mono />
        <MobileMetric label="用户评价" value={<RankingReviewSummary stationKey={station.key} reviewAverageRating={station.reviewAverageRating} reviewCount={station.reviewCount} />} />
      </div>

      <details className="mobile-card-details">
        <summary className="mobile-card-summary">
          <span>更多信息</span>
          <ChevronDown size={14} />
        </summary>
        <div className="mobile-card-detail-grid">
          <MobileDetail label="官方网址" value={<StationUrlLink href={stationExternalUrl} compact />} />
          <MobileDetail label="平台判断" value={station.platformGuess || "-"} />
          <MobileDetail label="站点类型" value={station.stationTypeLabel} />
          <MobileDetail label="未入榜原因" value={unrankedReason} />
          <MobileDetail label="核验档位" value={<span className="mono">{registryDisplay.verifiedTierCount}</span>} />
        </div>
      </details>

      <div className="mobile-card-actions">
        <Link href={`/stations/${station.key}`} prefetch={false} className="tiny-button mobile-card-button">
          详情
          <ChevronRight size={14} />
        </Link>
      </div>
    </article>
  );
}

export function RankingDashboard({ data, shell, pageViews }: { data: RankingPageData; shell: ShellData; pageViews: PageViewStats }) {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(data.defaultTimeWindow);
  const [sortMode, setSortMode] = useState<SortMode>(data.defaultSort);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [rankingPageSize, setRankingPageSize] = useState(10);
  const [rankingCurrentPage, setRankingCurrentPage] = useState(1);
  const [registryPageSize, setRegistryPageSize] = useState(10);
  const [registryCurrentPage, setRegistryCurrentPage] = useState(1);

  const stationMap = useMemo(() => new Map(data.stations.map((station) => [station.key, station])), [data.stations]);
  const unrankedStations = useMemo(() => {
    const rankedStationKeys = new Set(
      Object.values(data.rankings)
        .flatMap((rows) => rows.map((row) => row.station))
    );

    return data.stations
      .map((station, index) => ({ station, index, registryDisplay: getRegistryDisplayValues(station) }))
      .filter(({ station }) => !rankedStationKeys.has(station.key))
      .sort((left, right) => {
        if (left.registryDisplay.hasData !== right.registryDisplay.hasData) {
          return left.registryDisplay.hasData ? -1 : 1;
        }
        return left.index - right.index;
      })
      .map(({ station }) => station);
  }, [data.rankings, data.stations]);

  const activeRows = useMemo(() => {
    const rows = [...data.rankings[timeWindow]];
    const filtered = typeFilter === "all" ? rows : rows.filter((row) => row.stationType === typeFilter);
    filtered.sort((a, b) => compareByMode(a, b, sortMode));
    return filtered;
  }, [data.rankings, sortMode, timeWindow, typeFilter]);

  useEffect(() => {
    setRankingCurrentPage(1);
  }, [rankingPageSize, sortMode, timeWindow, typeFilter]);

  useEffect(() => {
    setRegistryCurrentPage(1);
  }, [registryPageSize, unrankedStations.length]);

  const rankingPageCount = Math.max(1, Math.ceil(activeRows.length / rankingPageSize));
  const safeRankingCurrentPage = Math.min(rankingCurrentPage, rankingPageCount);
  const rankingPageStartIndex = (safeRankingCurrentPage - 1) * rankingPageSize;
  const rankingPageEndIndex = Math.min(rankingPageStartIndex + rankingPageSize, activeRows.length);
  const paginatedRankingRows = activeRows.slice(rankingPageStartIndex, rankingPageEndIndex);
  const rankingDisplayStart = activeRows.length > 0 ? rankingPageStartIndex + 1 : 0;
  const rankingDisplayEnd = activeRows.length > 0 ? rankingPageEndIndex : 0;

  const registryPageCount = Math.max(1, Math.ceil(unrankedStations.length / registryPageSize));
  const safeRegistryCurrentPage = Math.min(registryCurrentPage, registryPageCount);
  const registryPageStartIndex = (safeRegistryCurrentPage - 1) * registryPageSize;
  const registryPageEndIndex = Math.min(registryPageStartIndex + registryPageSize, unrankedStations.length);
  const paginatedUnrankedStations = unrankedStations.slice(registryPageStartIndex, registryPageEndIndex);
  const registryDisplayStart = unrankedStations.length > 0 ? registryPageStartIndex + 1 : 0;
  const registryDisplayEnd = unrankedStations.length > 0 ? registryPageEndIndex : 0;

  const rankedCount = data.rankedStationCount[timeWindow];
  const selectedTypeLabel = TYPE_OPTIONS.find((option) => option.key === typeFilter)?.label ?? "全部类型";
  const selectedTimeWindow = data.timeWindows[timeWindow];

  return (
    <AppShell
      active="ranking"
      data={shell}
      topbarMetaClassName="topbar-meta-inline-mobile"
      footerMeta={
        <>
          累计 PV {formatCompactCount(pageViews.totalPv)}
        </>
      }
      actions={
        <>
          <StatusChip label={`收录站点 ${data.stations.length}`} tone="accent" />
          <StatusChip label={`当前时段 ${selectedTimeWindow.label}`} tone="blue" />
          <StatusChip label={`正式排名 ${rankedCount} 站`} tone="warn" />
        </>
      }
    >
        <section className="section ranking-section">
          <div className="section-head">
            <div>
              <h1 className="section-title">正式综合排名</h1>
              <p className="section-desc">同一时段内，请求样本数 ≥ 10 的站点优先排名，低样本站点仍保留在正式榜但整体置后。采用倍率按 Codex 口径最小非 0 分组倍率 × 实付金额 ÷ 到账美元额度计算；有明确用途标记时排除非 Codex 分组。目前安全审计与用户评分仅作为站点口碑参考展示，不参与综合分或正式排名计算；待验证方式与数据覆盖进一步完善后，将纳入排名权重。</p>
            </div>
            <div className="controls">
              <label className="control-group">
                <span className="control-label">时段</span>
                <select aria-label="时段" className="toolbar-select" value={timeWindow} onChange={(event) => setTimeWindow(event.target.value as TimeWindow)}>
                  {TIME_WINDOW_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="control-group">
                <span className="control-label">类型</span>
                <select aria-label="类型" className="toolbar-select" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}>
                  {TYPE_OPTIONS.map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="control-group">
                <span className="control-label">排序</span>
                <select aria-label="排序" className="toolbar-select" value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}>
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="section-body">
            <div className="desktop-table">
              <div className="table-wrap ranking-table-wrap">
                <table className="data-table ranking-table">
                  <colgroup>
                    <col className="ranking-col-rank" />
                    <col className="ranking-col-station" />
                    <col className="ranking-col-url" />
                    <col className="ranking-col-type" />
                    <col className="ranking-col-platform" />
                    <col className="ranking-col-metric" />
                    <col className="ranking-col-metric" />
                    <col className="ranking-col-metric" />
                    <col className="ranking-col-metric" />
                    <col className="ranking-col-metric" />
                    <col className="ranking-col-tier" />
                    <col className="ranking-col-review" />
                    <col className="ranking-col-action" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>排名</th>
                      <th>站点</th>
                      <th className="col-url">网址</th>
                      <th className="col-type">类型</th>
                      <th className="col-platform">平台判断</th>
                      <th>总分</th>
                      <th>请求样本数</th>
                      <th>正确率</th>
                      <th>平均响应时间</th>
                      <th>采用倍率</th>
                      <th>采用倍率档位</th>
                      <th>用户评分</th>
                      <th className="col-action">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedRankingRows.map((row, index) => {
                      const stationMeta = stationMap.get(row.station);
                      return (
                        <tr key={`${row.station}-${row.rank}`}>
                          <td className="mono">
                            <RankingPosition fallbackIndex={rankingPageStartIndex + index} />
                          </td>
                          <td>
                            <div className="table-cell-stack">
                              <div className="station-title-line">
                                <Link href={`/stations/${row.station}`} prefetch={false} className="station-link">
                                  {row.label}
                                </Link>
                                <CharityBadge stationType={row.stationType} />
                              </div>
                            </div>
                          </td>
                          <td className="table-url-cell">
                            <StationUrlLink href={row.stationUrl} compact />
                          </td>
                          <td className="table-type-cell">{row.stationTypeShortLabel}</td>
                          <td className="table-platform-cell">{stationMeta?.platformGuess || "-"}</td>
                          <td className="mono">{formatScore(row.totalScore)}</td>
                          <td className="mono">{row.requests}</td>
                          <td className="mono">{formatPercent(row.correctRate)}</td>
                          <td className="mono">{formatSeconds(row.avgSeconds)}s</td>
                          <td className="mono">{formatMultiplier(row.effectiveMultiplier)}</td>
                          <td>{row.adoptedTier}</td>
                          <td>
                            <RankingReviewSummary stationKey={row.station} reviewAverageRating={row.reviewAverageRating} reviewCount={row.reviewCount} />
                          </td>
                          <td className="table-action-cell">
                            <Link href={`/stations/${row.station}`} prefetch={false} className="tiny-button">
                              详情
                              <ChevronRight size={14} />
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mobile-card-list mobile-card-list-ranking">
              {paginatedRankingRows.map((row, index) => {
                const stationMeta = stationMap.get(row.station);
                return <MobileRankingCard key={`${row.station}-${row.rank}`} row={row} index={rankingPageStartIndex + index} stationMeta={stationMeta} />;
              })}
            </div>
            <TablePagination
              ariaLabel="正式综合排名分页"
              currentPage={safeRankingCurrentPage}
              displayEnd={rankingDisplayEnd}
              displayStart={rankingDisplayStart}
              onPageChange={setRankingCurrentPage}
              onPageSizeChange={(value) => {
                setRankingPageSize(value);
                setRankingCurrentPage(1);
              }}
              pageCount={rankingPageCount}
              pageSize={rankingPageSize}
              totalRows={activeRows.length}
            />
            <div className="footer-note">
              当前时段：{selectedTimeWindow.label}（{selectedTimeWindow.range}） · 排序：{SORT_OPTIONS.find((option) => option.value === sortMode)?.label} · 类型筛选：
              {selectedTypeLabel}
            </div>
          </div>
        </section>

        <section className="section registry-section">
          <div className="section-head">
            <div>
              <h2 className="section-title">未纳入正式排名的收录站点</h2>
              <p className="section-desc">仅展示在工作时段、非工作时段与全部时段三个正式排名中都未上榜的收录站点。</p>
            </div>
            <StatusChip label={`未纳入 ${unrankedStations.length} 站`} tone="accent" />
          </div>
          <div className="section-body">
            <div className="desktop-table">
              <div className="table-wrap">
                <table className="data-table registry-table">
                  <colgroup>
                    <col className="registry-col-station" />
                    <col className="registry-col-url" />
                    <col className="registry-col-type" />
                    <col className="registry-col-platform" />
                    <col className="registry-col-reason" />
                    <col className="registry-col-lowest-multiplier" />
                    <col className="registry-col-sample" />
                    <col className="registry-col-tier" />
                    <col className="registry-col-announcements" />
                    <col className="registry-col-review" />
                    <col className="registry-col-action" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>站点</th>
                      <th className="col-url">网址</th>
                      <th className="col-type">类型</th>
                      <th className="col-platform">平台判断</th>
                      <th>未入榜原因</th>
                      <th>最低倍率</th>
                      <th>全部时段样本</th>
                      <th>核验档位</th>
                      <th>公告数</th>
                      <th>用户评分</th>
                      <th className="col-action">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedUnrankedStations.map((station) => {
                      const unrankedReason = getUnrankedReason(station);
                      const registryDisplay = getRegistryDisplayValues(station);

                      return (
                        <tr key={station.key}>
                          <td>
                            <Link href={`/stations/${station.key}`} prefetch={false} className="station-link">
                              {station.label}
                            </Link>
                          </td>
                          <td className="table-url-cell">
                            <StationUrlLink href={station.stationExternalUrl} compact />
                          </td>
                          <td className="table-type-cell">{station.stationTypeShortLabel}</td>
                          <td className="table-platform-cell">{station.platformGuess || "-"}</td>
                          <td>{unrankedReason}</td>
                          <td className="mono">{registryDisplay.lowestMultiplier}</td>
                          <td className="mono">{registryDisplay.sampleCount}</td>
                          <td className="mono">{registryDisplay.verifiedTierCount}</td>
                          <td className="mono">{registryDisplay.announcementCount}</td>
                          <td>
                            <RankingReviewSummary stationKey={station.key} reviewAverageRating={station.reviewAverageRating} reviewCount={station.reviewCount} />
                          </td>
                          <td className="table-action-cell">
                            <Link href={`/stations/${station.key}`} prefetch={false} className="tiny-button">
                              详情
                              <ChevronRight size={14} />
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mobile-card-list mobile-card-list-stations">
              {paginatedUnrankedStations.map((station) => (
                <MobileStationCard key={station.key} station={station} />
              ))}
            </div>
            <TablePagination
              ariaLabel="未纳入正式排名的收录站点分页"
              currentPage={safeRegistryCurrentPage}
              displayEnd={registryDisplayEnd}
              displayStart={registryDisplayStart}
              onPageChange={setRegistryCurrentPage}
              onPageSizeChange={(value) => {
                setRegistryPageSize(value);
                setRegistryCurrentPage(1);
              }}
              pageCount={registryPageCount}
              pageSize={registryPageSize}
              totalRows={unrankedStations.length}
            />
          </div>
        </section>
    </AppShell>
  );
}
