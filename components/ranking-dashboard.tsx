"use client";

import { useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

import { formatMultiplier, formatPercent, formatScore, formatSeconds } from "@/lib/format";
import type { RankingRow, SiteData, SortMode, TimeWindow } from "@/lib/types";
import { AppShell, StatusChip } from "@/components/app-shell";

const HIGHLIGHT_PHRASE = "所以本排名更关注各中转站的服务下限。";
const DISCLAIMER_EMPHASIS = "本排名无任何利益相关，仅供参考。";

const TIME_WINDOW_OPTIONS: Array<{ value: TimeWindow; label: string }> = [
  { value: "all_hours", label: "全部时段" },
  { value: "work_hours", label: "工作时段" },
  { value: "off_hours", label: "非工作时段" }
];

const SORT_OPTIONS: Array<{ value: SortMode; label: string }> = [
  { value: "composite", label: "综合排序" },
  { value: "correct_rate", label: "正确率优先" },
  { value: "avg_seconds", label: "响应时间优先" },
  { value: "effective_multiplier", label: "采用倍率优先" }
];

const TYPE_OPTIONS = [
  { key: "all", label: "全部类型" },
  { key: "subscription", label: "包月型" },
  { key: "non_subscription", label: "非包月型" },
  { key: "mixed", label: "混合型" }
] as const;

type TypeFilter = (typeof TYPE_OPTIONS)[number]["key"];

function compareByMode(rowA: RankingRow, rowB: RankingRow, mode: SortMode): number {
  if (mode === "correct_rate") {
    return rowB.correctRate - rowA.correctRate || rowA.avgSeconds - rowB.avgSeconds || rowA.effectiveMultiplier - rowB.effectiveMultiplier || rowA.rank - rowB.rank;
  }
  if (mode === "avg_seconds") {
    return rowA.avgSeconds - rowB.avgSeconds || rowB.correctRate - rowA.correctRate || rowA.effectiveMultiplier - rowB.effectiveMultiplier || rowA.rank - rowB.rank;
  }
  if (mode === "effective_multiplier") {
    return rowA.effectiveMultiplier - rowB.effectiveMultiplier || rowB.totalScore - rowA.totalScore || rowA.rank - rowB.rank;
  }
  return rowB.totalScore - rowA.totalScore || rowA.rank - rowB.rank;
}

function getOfficialUrl(href: string) {
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

  const resolvedHref = compact ? getOfficialUrl(href) : href;

  return (
    <a href={resolvedHref} target="_blank" rel="noreferrer" className="station-link inline-actions">
      <span>{resolvedHref}</span>
      <ExternalLink size={14} />
    </a>
  );
}

function getStationTone(stationType: RankingRow["stationType"]): "default" | "accent" | "blue" | "warn" {
  if (stationType === "subscription") {
    return "blue";
  }
  if (stationType === "non_subscription") {
    return "warn";
  }
  if (stationType === "mixed") {
    return "accent";
  }
  return "default";
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

function getTotalSampleCount(station: SiteData["stations"][number]) {
  const workRequests = station.rankings.work_hours?.requests;
  const offRequests = station.rankings.off_hours?.requests;

  if (workRequests == null && offRequests == null) {
    return null;
  }

  return (workRequests ?? 0) + (offRequests ?? 0);
}

function MobileRankingCard({ row, index, stationMeta }: { row: RankingRow; index: number; stationMeta?: { platformGuess: string } }) {
  return (
    <article className="mobile-card">
      <div className="mobile-card-header">
        <div className="mobile-card-lead">
          <div className="mobile-card-rank mono">{index + 1}</div>
          <div className="mobile-card-title-block">
            <Link href={`/stations/${row.station}`} className="station-link mobile-card-title">
              {row.label}
            </Link>
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
          <MobileDetail label="倍率口径" value={row.multiplierFullUseAssumption} />
          <MobileDetail label="请求样本" value={<span className="mono">{row.requests}</span>} />
        </div>
      </details>

      <div className="mobile-card-actions">
        <Link href={`/stations/${row.station}`} className="tiny-button mobile-card-button">
          详情
          <ChevronRight size={14} />
        </Link>
      </div>
    </article>
  );
}

function MobileStationCard({ station }: { station: SiteData["stations"][number] }) {
  const totalRequests = getTotalSampleCount(station);

  return (
    <article className="mobile-card">
      <div className="mobile-card-header">
        <div className="mobile-card-lead">
          <div className="mobile-card-title-block">
            <Link href={`/stations/${station.key}`} className="station-link mobile-card-title">
              {station.label}
            </Link>
            <span className="mobile-card-subtitle">{station.platformGuess || "-"}</span>
          </div>
        </div>
        <StatusChip label={station.stationTypeShortLabel} tone={getStationTone(station.stationType)} />
      </div>

      <div className="mobile-metrics-grid">
        <MobileMetric label="工作样本" value={<span className="mono">{station.rankings.work_hours?.requests ?? "-"}</span>} />
        <MobileMetric label="非工作样本" value={<span className="mono">{station.rankings.off_hours?.requests ?? "-"}</span>} />
        <MobileMetric label="总样本数" value={<span className="mono">{totalRequests ?? "-"}</span>} />
        <MobileMetric label="公告数量" value={<span className="mono">{station.announcements.length}</span>} />
      </div>

      <details className="mobile-card-details" open>
        <summary className="mobile-card-summary">
          <span>更多信息</span>
          <ChevronDown size={14} />
        </summary>
        <div className="mobile-card-detail-grid">
          <MobileDetail label="官方网址" value={<StationUrlLink href={station.url} compact />} />
          <MobileDetail label="平台判断" value={station.platformGuess || "-"} />
          <MobileDetail label="站点类型" value={station.stationTypeLabel} />
          <MobileDetail label="核验档位" value={<span className="mono">{station.verifiedTierCount}</span>} />
        </div>
      </details>

      <div className="mobile-card-actions">
        <Link href={`/stations/${station.key}`} className="tiny-button mobile-card-button">
          查看
          <ChevronRight size={14} />
        </Link>
      </div>
    </article>
  );
}

function normalizeDeclarationText(text: string) {
  return text.replace(`（${HIGHLIGHT_PHRASE}）`, HIGHLIGHT_PHRASE);
}

function renderEmphasizedText(text: string) {
  if (text.includes(HIGHLIGHT_PHRASE)) {
    const [before, after] = text.split(HIGHLIGHT_PHRASE, 2);
    return (
      <>
        {before}
        所以
        <strong>本排名更关注各中转站的服务下限。</strong>
        {after}
      </>
    );
  }

  if (text.includes(DISCLAIMER_EMPHASIS)) {
    const [before, after] = text.split(DISCLAIMER_EMPHASIS, 2);
    return (
      <>
        {before}
        <strong>{DISCLAIMER_EMPHASIS}</strong>
        {after}
      </>
    );
  }

  return text;
}

function splitStatementLine(item: string) {
  for (const separator of ["：", "=", ":"]) {
    if (item.includes(separator)) {
      const [label, value] = item.split(separator, 2);
      return { label: label.trim(), value: value.trim() };
    }
  }

  return { label: "", value: item.trim() };
}

function StatementList({ items }: { items: string[] }) {
  return (
    <div className="statement-list">
      {items.map((item) => {
        const { label, value } = splitStatementLine(item);
        return (
          <div className="statement-row" key={item}>
            {label ? <p className="statement-label">{label}</p> : null}
            <p className="statement-value">{label ? renderEmphasizedText(value) : renderEmphasizedText(item)}</p>
          </div>
        );
      })}
    </div>
  );
}

function BulletTextList({ items }: { items: string[] }) {
  return (
    <div className="bullet-list">
      {items.map((item) => (
        <div className="bullet-item" key={item}>
          <span className="bullet-prefix">-</span>
          <p className="bullet-copy">{renderEmphasizedText(item)}</p>
        </div>
      ))}
    </div>
  );
}

export function DeclarationPanels({ data }: { data: SiteData }) {
  const coreItems =
    data.declaration.coreItems && data.declaration.coreItems.length
      ? data.declaration.coreItems
      : [data.declaration.scoring, data.declaration.formula, data.declaration.adoptedMultiplierRule].filter(Boolean);
  const conclusionItems = data.declaration.conclusion ?? [];
  const environmentParagraphs = data.declaration.environment
    .split(/\n{2,}/)
    .map((item) => normalizeDeclarationText(item.trim()))
    .filter(Boolean);

  return (
    <div className="declaration-layout">
      <div className="declaration-columns">
        <div className="declaration-side">
          <div className="notice-panel declaration-copy-panel declaration-copy-full">
            <p className="notice-title">环境与口径</p>
            <BulletTextList items={environmentParagraphs} />
          </div>
        </div>

        <div className="declaration-side declaration-side-split">
          <div className="notice-panel declaration-compact-panel">
            <p className="notice-title">核心公式</p>
            <StatementList items={coreItems} />
          </div>
          <div className="notice-panel declaration-compact-panel">
            <p className="notice-title">补充说明</p>
            <StatementList items={data.declaration.items} />
          </div>
        </div>
      </div>

      {conclusionItems.length ? (
        <div className="notice-panel notice-panel-primary declaration-hero">
          <p className="notice-title">最终结论</p>
          <BulletTextList items={conclusionItems} />
        </div>
      ) : null}
    </div>
  );
}

export function RankingDashboard({ data }: { data: SiteData }) {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(data.defaultTimeWindow);
  const [sortMode, setSortMode] = useState<SortMode>(data.defaultSort);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");

  const stationMap = useMemo(() => new Map(data.stations.map((station) => [station.key, station])), [data.stations]);
  const unrankedStations = useMemo(() => {
    const rankedStationKeys = new Set(
      Object.values(data.rankings)
        .flatMap((rows) => rows.map((row) => row.station))
    );

    return data.stations.filter((station) => !rankedStationKeys.has(station.key));
  }, [data.rankings, data.stations]);

  const activeRows = useMemo(() => {
    const rows = [...data.rankings[timeWindow]];
    const filtered = typeFilter === "all" ? rows : rows.filter((row) => row.stationType === typeFilter);
    filtered.sort((a, b) => compareByMode(a, b, sortMode));
    return filtered;
  }, [data.rankings, sortMode, timeWindow, typeFilter]);

  const rankedCount = data.rankedStationCount[timeWindow];
  const selectedTypeLabel = TYPE_OPTIONS.find((option) => option.key === typeFilter)?.label ?? "全部类型";
  const selectedTimeWindow = data.timeWindows[timeWindow];

  return (
    <AppShell
      active="ranking"
      data={data}
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
              <p className="section-desc">支持工作时段与非工作时段切换；周末样本统一计入非工作时段。采用倍率按 Codex 口径最小非 0 分组倍率 × 实付人民币 ÷ 到账美元额度计算，`default` 分组也按 Codex 可用分组处理。</p>
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
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>排名</th>
                      <th>站点</th>
                      <th className="col-url">网址</th>
                      <th className="col-type">类型</th>
                      <th className="col-platform">平台判断</th>
                      <th>总分</th>
                      <th>正确率</th>
                      <th>平均响应时间（秒）</th>
                      <th>采用倍率</th>
                      <th>采用倍率档位</th>
                      <th>倍率口径</th>
                      <th>请求样本数</th>
                      <th className="col-action">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeRows.map((row, index) => {
                      const stationMeta = stationMap.get(row.station);
                      return (
                        <tr key={`${row.station}-${row.rank}`}>
                          <td className="mono">{index + 1}</td>
                          <td>
                            <div className="table-cell-stack">
                              <Link href={`/stations/${row.station}`} className="station-link">
                                {row.label}
                              </Link>
                            </div>
                          </td>
                          <td className="table-url-cell">
                            <StationUrlLink href={row.stationUrl} compact />
                          </td>
                          <td className="table-type-cell">{row.stationTypeShortLabel}</td>
                          <td className="table-platform-cell">{stationMeta?.platformGuess || "-"}</td>
                          <td className="mono">{formatScore(row.totalScore)}</td>
                          <td className="mono">{formatPercent(row.correctRate)}</td>
                          <td className="mono">{formatSeconds(row.avgSeconds)}</td>
                          <td className="mono">{formatMultiplier(row.effectiveMultiplier)}</td>
                          <td>{row.adoptedTier}</td>
                          <td>{row.multiplierFullUseAssumption}</td>
                          <td className="mono">{row.requests}</td>
                          <td className="table-action-cell">
                            <Link href={`/stations/${row.station}`} className="tiny-button">
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
              {activeRows.map((row, index) => {
                const stationMeta = stationMap.get(row.station);
                return <MobileRankingCard key={`${row.station}-${row.rank}`} row={row} index={index} stationMeta={stationMeta} />;
              })}
            </div>
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
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>站点</th>
                      <th className="col-url">网址</th>
                      <th className="col-type">类型</th>
                      <th>平台判断</th>
                      <th>工作时段样本</th>
                      <th>非工作时段样本</th>
                      <th>总样本数</th>
                      <th>核验档位</th>
                      <th>公告数</th>
                      <th className="col-action">详情</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unrankedStations.map((station) => {
                      const totalRequests = getTotalSampleCount(station);

                      return (
                        <tr key={station.key}>
                          <td>
                            <Link href={`/stations/${station.key}`} className="station-link">
                              {station.label}
                            </Link>
                          </td>
                          <td className="table-url-cell">
                            <StationUrlLink href={station.url} compact />
                          </td>
                          <td className="table-type-cell">{station.stationTypeShortLabel}</td>
                          <td>{station.platformGuess || "-"}</td>
                          <td className="mono">{station.rankings.work_hours?.requests ?? "-"}</td>
                          <td className="mono">{station.rankings.off_hours?.requests ?? "-"}</td>
                          <td className="mono">{totalRequests ?? "-"}</td>
                          <td className="mono">{station.verifiedTierCount}</td>
                          <td className="mono">{station.announcements.length}</td>
                          <td className="table-action-cell">
                            <Link href={`/stations/${station.key}`} className="tiny-button">
                              查看
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
              {unrankedStations.map((station) => (
                <MobileStationCard key={station.key} station={station} />
              ))}
            </div>
          </div>
        </section>
    </AppShell>
  );
}
