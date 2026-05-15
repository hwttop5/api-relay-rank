"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ChevronUp, ExternalLink, ShieldCheck } from "lucide-react";

import { formatDateTime, formatMultiplier, formatPercent, formatScore, formatSeconds } from "@/lib/format";
import type { RankingRow, SiteData, SortMode, TimeWindow } from "@/lib/types";

const HIGHLIGHT_PHRASE = "所以此排名关注的是中转站的的服务下限";

const TIME_WINDOW_OPTIONS: Array<{ value: TimeWindow; label: string }> = [
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

function StatusChip({ label, tone = "default" }: { label: string; tone?: "default" | "accent" | "blue" | "warn" }) {
  const cls = tone === "accent" ? "chip chip-accent" : tone === "blue" ? "chip chip-blue" : tone === "warn" ? "chip chip-warn" : "chip";
  return <span className={cls}>{label}</span>;
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

function renderEnvironment(text: string) {
  const normalized = text.replace(`（${HIGHLIGHT_PHRASE}）`, HIGHLIGHT_PHRASE);
  if (!normalized.includes(HIGHLIGHT_PHRASE)) {
    return <p className="notice-copy">{normalized}</p>;
  }

  const [before, after] = normalized.split(HIGHLIGHT_PHRASE);
  return (
    <p className="notice-copy">
      {before}
      <strong>{HIGHLIGHT_PHRASE}</strong>
      {after}
    </p>
  );
}

export function RankingDashboard({ data }: { data: SiteData }) {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(data.defaultTimeWindow);
  const [sortMode, setSortMode] = useState<SortMode>(data.defaultSort);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [declarationOpen, setDeclarationOpen] = useState(true);

  const stationMap = useMemo(() => new Map(data.stations.map((station) => [station.key, station])), [data.stations]);

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
    <main className="app-shell">
      <div className="page-shell">
        <header className="topbar">
          <div className="brand">
            <div className="brand-title">
              <ShieldCheck size={18} />
              <span>{data.siteName}</span>
            </div>
            <div className="brand-subtitle">
              {data.projectName} · 数据生成于 {formatDateTime(data.generatedAt)}
            </div>
          </div>
          <div className="topbar-meta">
            <StatusChip label={`收录站点 ${data.stations.length}`} tone="accent" />
            <StatusChip label={`当前窗口 ${selectedTimeWindow.label}`} tone="blue" />
            <StatusChip label={`正式排名 ${rankedCount} 站`} tone="warn" />
          </div>
        </header>

        <section className="section">
          <div className="section-head ranking-head">
            <div>
              <h1 className="section-title">{data.declaration.title}</h1>
              <p className="section-desc">{data.declaration.subtitle}</p>
            </div>
            <div className="section-head-actions">
              <StatusChip label={`采集时间 ${data.generatedAt || "未知"}`} tone="accent" />
              <button type="button" className="tiny-button" aria-expanded={declarationOpen} onClick={() => setDeclarationOpen((current) => !current)}>
                {declarationOpen ? "收起" : "展开"}
                {declarationOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
            </div>
          </div>
          {declarationOpen ? (
            <div className="section-body">
              <div className="notice-grid">
                <div className="notice-panel">
                  <p className="notice-title">环境与口径</p>
                  {renderEnvironment(data.declaration.environment)}
                </div>
                <div className="notice-panel">
                  <p className="notice-title">核心公式</p>
                  <ul className="notice-list">
                    <li>{data.declaration.formula}</li>
                    <li>{data.declaration.adoptedMultiplierRule}</li>
                    <li>{data.declaration.scoring}</li>
                  </ul>
                </div>
                <div className="notice-panel">
                  <p className="notice-title">补充说明</p>
                  <ul className="notice-list">
                    {data.declaration.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          ) : null}
        </section>

        <section className="section">
          <div className="section-head">
            <div>
              <h2 className="section-title">正式综合排名</h2>
              <p className="section-desc">支持工作时段与非工作时段切换，并按站点类型、排序方式重新排列。</p>
            </div>
            <div className="controls">
              <label className="control-group">
                <span className="control-label">窗口</span>
                <select aria-label="窗口" className="toolbar-select" value={timeWindow} onChange={(event) => setTimeWindow(event.target.value as TimeWindow)}>
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
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>站点</th>
                    <th className="col-url">网址</th>
                    <th className="col-type">类型</th>
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
                            <span className="subtle">{stationMeta?.platformGuess || "-"}</span>
                          </div>
                        </td>
                        <td className="table-url-cell">
                          <StationUrlLink href={row.stationUrl} compact />
                        </td>
                        <td className="table-type-cell">{row.stationTypeShortLabel}</td>
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
            <div className="footer-note">
              当前窗口：{selectedTimeWindow.label}（{selectedTimeWindow.range}） · 排序：{SORT_OPTIONS.find((option) => option.value === sortMode)?.label} · 类型筛选：
              {selectedTypeLabel}
            </div>
          </div>
        </section>

        <section className="section">
          <div className="section-head">
            <div>
              <h2 className="section-title">全部收录站点</h2>
              <p className="section-desc">点击站点名称进入详情页，查看对应站点的全部档位倍率表和最新公告。</p>
            </div>
            <StatusChip label={`已收录 ${data.stations.length} 站`} tone="accent" />
          </div>
          <div className="section-body">
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
                    <th>公告数</th>
                    <th className="col-action">详情</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stations.map((station) => (
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
                      <td className="mono">{station.announcements.length}</td>
                      <td className="table-action-cell">
                        <Link href={`/stations/${station.key}`} className="tiny-button">
                          查看
                          <ChevronRight size={14} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="section">
          <div className="section-head">
            <div>
              <h2 className="section-title">基础口径</h2>
              <p className="section-desc">用于快速说明时间窗口、评分权重和采用倍率的公共口径。</p>
            </div>
          </div>
          <div className="section-body">
            <div className="detail-grid">
              <div className="detail-card">
                <h3>工作时段</h3>
                <p>09:00:00 - 18:00:00</p>
              </div>
              <div className="detail-card">
                <h3>非工作时段</h3>
                <p>18:00:01 - 次日 08:59:59</p>
              </div>
              <div className="detail-card">
                <h3>排名权重</h3>
                <p>正确响应率 40% · 响应时间 35% · 采用倍率 25%</p>
              </div>
              <div className="detail-card">
                <h3>采用倍率公式</h3>
                <p>实际倍率 = 分组倍率 × 实付人民币金额 ÷ 到账美元额度</p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
