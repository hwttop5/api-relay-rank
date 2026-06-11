import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { AppShell, StatusChip } from "@/components/app-shell";
import { AnnouncementFeed } from "@/components/announcement-feed";
import { StationAuditSummaryPanel } from "@/components/station-audit-summary";
import { StationFeedbackActions, StationFeedbackProvider, StationReviewSection } from "@/components/station-feedback-panel";
import { TierOverview } from "@/components/tier-overview";
import { formatCompactCount, formatDateTime, formatMultiplier, formatPercent, formatScore, formatSeconds } from "@/lib/format";
import { localizeStationAuditText } from "@/lib/audit-localization";
import { getPageViewStats } from "@/lib/page-view-stats";
import { hasDatabaseUrl, readStationReviewPage } from "@/lib/postgres";
import { absoluteUrl, findBestRanking, pageMetadata, safeJsonLd, stationMetadataDescription, stationPageTitle } from "@/lib/seo";
import { getSiteData, getStationRecord } from "@/lib/site-data";
import { buildShellData } from "@/lib/site-data-view";
import { emptyReviewSummary } from "@/lib/user-feedback";

export const revalidate = 300;

function stationTypeTone(stationType: string): "default" | "accent" | "blue" | "warn" | "success" {
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

export async function generateStaticParams() {
  const siteData = await getSiteData();
  return siteData.stations.map((station) => ({ station: station.key }));
}

export async function generateMetadata({ params }: { params: Promise<{ station: string }> }) {
  const resolvedParams = await params;
  const { station } = await getStationRecord(resolvedParams.station);
  return pageMetadata({
    title: stationPageTitle(station),
    description: stationMetadataDescription(station),
    pathname: `/stations/${station.key}`,
  });
}

export default async function StationPage({ params }: { params: Promise<{ station: string }> }) {
  const resolvedParams = await params;
  const [{ siteData: rawSiteData, station: rawStation }, pageViewStats] = await Promise.all([
    getStationRecord(resolvedParams.station),
    getPageViewStats(),
  ]);
  const initialReviewPage = hasDatabaseUrl()
    ? await readStationReviewPage(rawStation.key, null).then(
        (page) => ({ ...page, viewer: null, viewerReview: null }),
        () => ({
          summary: emptyReviewSummary(rawStation.key),
          reviews: [],
          pagination: { limit: 10, offset: 0, nextOffset: null, hasMore: false },
          viewer: null,
          viewerReview: null,
        }),
      )
    : {
        summary: emptyReviewSummary(rawStation.key),
        reviews: [],
        pagination: { limit: 10, offset: 0, nextOffset: null, hasMore: false },
        viewer: null,
        viewerReview: null,
      };
  const station = localizeStationAuditText(rawStation);
  const shellData = buildShellData(rawSiteData, rawSiteData.stations.length);
  const stationTone = stationTypeTone(station.stationType);
  const stationPageViews = pageViewStats.stationPv[station.key] ?? 0;

  const work = station.rankings.work_hours;
  const off = station.rankings.off_hours;
  const bestRanking = findBestRanking(station);
  const latestAnnouncements = [...station.announcements].sort((a, b) => (a.publishedAt < b.publishedAt ? 1 : -1)).slice(0, 5);
  const announcementEvidence = station.dataEvidence?.find((item) => item.key === "announcements");
  const stationExternalUrl = station.inviteUrl || station.url;
  const announcementEmptyText = announcementEvidence?.status === "empty"
    ? "暂无公告数据"
    : announcementEvidence
      ? `${announcementEvidence.statusLabel}：${announcementEvidence.message}`
      : "暂未抓到可展示公告内容。";
  const stationDescription = `${station.label} 是 ${station.stationTypeShortLabel}，平台判断为 ${
    station.platformGuess || "平台未识别"
  }。这里展示该站点的正式排名快照、全部档位倍率表、安全审计和最新公告。`;
  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      {
        "@type": "ListItem",
        position: 1,
        name: "综合排名",
        item: absoluteUrl("/ranking"),
      },
      {
        "@type": "ListItem",
        position: 2,
        name: station.label,
        item: absoluteUrl(`/stations/${encodeURIComponent(station.key)}`),
      },
    ],
  };
  const webPageJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: stationPageTitle(station),
    description: stationMetadataDescription(station),
    url: absoluteUrl(`/stations/${encodeURIComponent(station.key)}`),
    isPartOf: {
      "@type": "WebSite",
      name: rawSiteData.siteName,
      url: absoluteUrl("/ranking"),
    },
    about: {
      "@type": "Thing",
      name: station.label,
      url: station.url || absoluteUrl(`/stations/${encodeURIComponent(station.key)}`),
    },
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(breadcrumbJsonLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(webPageJsonLd) }} />
      <StationFeedbackProvider stationKey={station.key} stationLabel={station.label} initialReviewPage={initialReviewPage}>
        <AppShell
          active="station"
          data={shellData}
          title={station.label}
          subtitle={`${station.stationTypeShortLabel} · ${station.platformGuess || "平台未识别"} · ${rawSiteData.projectName}`}
          footerMeta={
            <>
              累计 PV {formatCompactCount(pageViewStats.totalPv)}
            </>
          }
          actions={
            <>
              <StatusChip label={station.stationTypeLabel} tone={stationTone} />
              <div className="station-topbar-links">
                <Link href="/ranking" className="tiny-button detail-topbar-button">
                  <ArrowLeft size={13} />
                  返回排名
                </Link>
                {stationExternalUrl ? (
                  <a href={stationExternalUrl} target="_blank" rel="noreferrer" className="tiny-button detail-topbar-button">
                    <ExternalLink size={13} />
                    打开官网
                  </a>
                ) : null}
              </div>
            </>
          }
        >
          <section className="section station-hero">
            <div className="section-head">
              <div>
                <h1 className="section-title">{stationPageTitle(station)}</h1>
                <p className="section-desc">{stationDescription}</p>
              </div>
              <StatusChip label={station.stationTypeLabel} tone={stationTone} />
            </div>
            <div className="section-body">
              <div className="detail-grid">
                <div className="detail-card">
                  <h3>平台判断</h3>
                  <p>{station.platformGuess || "平台未识别"}</p>
                </div>
                <div className="detail-card">
                  <h3>公告数量</h3>
                  <p>{station.announcements.length}</p>
                </div>
                <div className="detail-card">
                  <h3>详情页 PV</h3>
                  <p>{formatCompactCount(stationPageViews)}</p>
                </div>
                <div className="detail-card">
                  <h3>工作时段排名</h3>
                  <p>{work ? `#${work.rank} · ${formatScore(work.totalScore)} · ${formatPercent(work.correctRate)}` : "暂无正式排名数据"}</p>
                </div>
                <div className="detail-card">
                  <h3>非工作时段排名</h3>
                  <p>{off ? `#${off.rank} · ${formatScore(off.totalScore)} · ${formatPercent(off.correctRate)}` : "暂无正式排名数据"}</p>
                </div>
              </div>
              <div className="station-hero-footer">
                <div className="footer-note">
                  站点代号：{station.key} · 数据生成于 {formatDateTime(rawSiteData.generatedAt)} · 已核验档位数：{station.verifiedTierCount}
                  {bestRanking ? ` · 全时段排名 #${bestRanking.rank}` : ""}
                </div>
                <StationFeedbackActions />
              </div>
            </div>
          </section>

          <StationAuditSummaryPanel station={station} />

          <section className="section tier-section">
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

          <section className="section announcement-section">
            <div className="section-head">
              <div>
                <h2 className="section-title">最新公告</h2>
                <p className="section-desc">按公开页面或登录态 probe 抓取并保留最新 5 条。</p>
              </div>
            </div>
            <div className="section-body">
              <AnnouncementFeed announcements={latestAnnouncements} emptyText={announcementEmptyText} />
            </div>
          </section>

          <section className="section snapshot-section">
            <div className="section-head">
              <div>
                <h2 className="section-title">排名快照</h2>
                <p className="section-desc">展示该站点在两个核心时间窗口下的正式排名指标。</p>
              </div>
            </div>
            <div className="section-body">
              <div className="grid-2">
                {([
                  ["work_hours", work, "工作时段（工作日09:00:00-18:00:00）"],
                  ["off_hours", off, "非工作时段（工作日18:00:01-次日08:59:59，周末全天）"],
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
                        <p>倍率口径：{row.multiplierFullUseAssumption}</p>
                      </div>
                    ) : (
                      <p>暂无正式排名数据。</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <StationReviewSection />
        </AppShell>
      </StationFeedbackProvider>
    </>
  );
}
