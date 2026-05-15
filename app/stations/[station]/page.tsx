import Link from "next/link";
import { ArrowLeft, ExternalLink, ShieldCheck } from "lucide-react";

import { AnnouncementFeed } from "@/components/announcement-feed";
import { TierOverview } from "@/components/tier-overview";
import { formatDateTime, formatMultiplier, formatPercent, formatScore, formatSeconds } from "@/lib/format";
import { getStationRecord } from "@/lib/site-data";

export const dynamic = "force-dynamic";

function getOfficialUrl(href: string) {
  try {
    return new URL(href).origin;
  } catch {
    return href;
  }
}

function StationUrlLink({ href }: { href: string }) {
  if (!href) {
    return <span className="subtle">未记录</span>;
  }

  const resolvedHref = getOfficialUrl(href);

  return (
    <a href={resolvedHref} target="_blank" rel="noreferrer" className="station-link inline-actions">
      <span>{resolvedHref}</span>
      <ExternalLink size={14} />
    </a>
  );
}

export default async function StationPage({ params }: { params: Promise<{ station: string }> }) {
  const resolvedParams = await params;
  const { siteData, station } = await getStationRecord(resolvedParams.station);

  const work = station.rankings.work_hours;
  const off = station.rankings.off_hours;
  const latestAnnouncements = [...station.announcements].sort((a, b) => (a.publishedAt < b.publishedAt ? 1 : -1)).slice(0, 5);

  return (
    <main className="app-shell">
      <div className="page-shell">
        <header className="topbar">
          <div className="brand">
            <div className="brand-title">
              <ShieldCheck size={18} />
              <span>{station.label}</span>
            </div>
            <div className="brand-subtitle">
              {station.stationTypeShortLabel} · {station.platformGuess || "平台未识别"} · {siteData.projectName}
            </div>
          </div>
          <div className="topbar-meta">
            <Link href="/" className="tiny-button">
              <ArrowLeft size={14} />
              返回排名
            </Link>
            {station.url ? (
              <a href={station.url} target="_blank" rel="noreferrer" className="tiny-button">
                <ExternalLink size={14} />
                打开官网
              </a>
            ) : null}
          </div>
        </header>

        <section className="section">
          <div className="section-head">
            <div>
              <h1 className="section-title">站点详情</h1>
              <p className="section-desc">这里展示该站点的正式排名快照、全部档位倍率表和最新公告。</p>
            </div>
            <span className="chip chip-accent">{station.stationTypeLabel}</span>
          </div>
          <div className="section-body">
            <div className="detail-grid">
              <div className="detail-card">
                <h3>网址</h3>
                <p>
                  <StationUrlLink href={station.url} />
                </p>
              </div>
              <div className="detail-card">
                <h3>工作时段排名</h3>
                <p>{work ? `#${work.rank} · ${formatScore(work.totalScore)} · ${formatPercent(work.correctRate)}` : "暂无正式排名数据"}</p>
              </div>
              <div className="detail-card">
                <h3>非工作时段排名</h3>
                <p>{off ? `#${off.rank} · ${formatScore(off.totalScore)} · ${formatPercent(off.correctRate)}` : "暂无正式排名数据"}</p>
              </div>
              <div className="detail-card">
                <h3>公告数量</h3>
                <p>{station.announcements.length}</p>
              </div>
            </div>
            <div className="footer-note">
              站点代号：{station.key} · 数据生成于 {formatDateTime(siteData.generatedAt)} · 已核验档位数：{station.verifiedTierCount}
            </div>
          </div>
        </section>

        <section className="section">
          <div className="section-head">
            <div>
              <h2 className="section-title">全部档位倍率表</h2>
              <p className="section-desc">上方为分组倍率，下方为充值档位。这里不展开排列组合，只保留站点当前可见的全部档位。</p>
            </div>
          </div>
          <div className="section-body">
            <TierOverview groups={station.groupMultipliers} rechargeTiers={station.rechargeTiers} />
          </div>
        </section>

        <section className="section">
          <div className="section-head">
            <div>
              <h2 className="section-title">最新公告</h2>
              <p className="section-desc">按公开页面抓取并保留最新 5 条。</p>
            </div>
          </div>
          <div className="section-body">
            <AnnouncementFeed announcements={latestAnnouncements} />
          </div>
        </section>

        <section className="section">
          <div className="section-head">
            <div>
              <h2 className="section-title">排名快照</h2>
              <p className="section-desc">展示该站点在两个核心时间窗口下的正式排名指标。</p>
            </div>
          </div>
          <div className="section-body">
            <div className="grid-2">
              {([
                ["work_hours", work, "工作时段（09:00:00-18:00:00）"],
                ["off_hours", off, "非工作时段（18:00:01-次日08:59:59）"]
              ] as const).map(([key, row, title]) => (
                <div className="detail-card" key={key}>
                  <h3>{title}</h3>
                  {row ? (
                    <div className="stack">
                      <p>排名：#{row.rank}</p>
                      <p>总分：{formatScore(row.totalScore)}</p>
                      <p>正确率：{formatPercent(row.correctRate)}</p>
                      <p>平均响应时间（秒）：{formatSeconds(row.avgSeconds)}</p>
                      <p>采用倍率：{formatMultiplier(row.effectiveMultiplier)}</p>
                      <p>采用档位：{row.adoptedTier}</p>
                    </div>
                  ) : (
                    <p>暂无正式排名数据。</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
