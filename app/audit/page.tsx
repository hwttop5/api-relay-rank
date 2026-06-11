import { AppShell, StatusChip } from "@/components/app-shell";
import { AuditInteraction } from "@/components/audit-interaction";
import { AUDIT_FAQ_ITEMS, AuditFaqContent, AuditSeoContent } from "@/components/audit-seo-content";
import { getAuditHistoryPage, parseAuditHistorySearchParams } from "@/lib/audit-history";
import { localizeAuditHistoryItemText } from "@/lib/audit-localization";
import { formatCompactCount } from "@/lib/format";
import { getPageViewStats } from "@/lib/page-view-stats";
import { absoluteUrl, pageMetadata, safeJsonLd } from "@/lib/seo";
import { getSiteData } from "@/lib/site-data";
import { buildShellData } from "@/lib/site-data-view";

const PAGE_TITLE = "AI 中转站安全审计";
const PAGE_DESCRIPTION = "输入 AI 中转站 API 地址和临时 API Key，执行本地黑盒安全审计，查看风险等级、审计摘要和历史报告。";

export const dynamic = "force-dynamic";

export const metadata = pageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  pathname: "/audit",
});

type AuditPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AuditPage({ searchParams }: AuditPageProps) {
  const auditHistoryFilters = parseAuditHistorySearchParams(await searchParams);
  const [rawSiteData, pageViewStats] = await Promise.all([getSiteData(), getPageViewStats()]);
  const shellData = buildShellData(rawSiteData, rawSiteData.stations.length);
  const auditHistoryPage = await getAuditHistoryPage(rawSiteData, auditHistoryFilters);
  const localizedAuditHistoryPage = {
    ...auditHistoryPage,
    items: auditHistoryPage.items.map(localizeAuditHistoryItemText),
  };
  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: AUDIT_FAQ_ITEMS.map((item) => ({
      "@type": "Question",
      name: item.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: item.answer,
      },
    })),
  };
  const webPageJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: PAGE_TITLE,
    description: PAGE_DESCRIPTION,
    url: absoluteUrl("/audit"),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(webPageJsonLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(faqJsonLd) }} />
      <AppShell
        active="audit"
        data={shellData}
        footerMeta={<>累计 PV {formatCompactCount(pageViewStats.totalPv)}</>}
        topbarMetaClassName="topbar-meta-inline-mobile"
        actions={
          <>
            <StatusChip label={`收录站点 ${rawSiteData.stations.length}`} tone="accent" />
            <StatusChip label={`历史记录 ${localizedAuditHistoryPage.total}`} tone="warn" />
            <StatusChip label="主动黑盒审计" tone="blue" />
          </>
        }
      >
        <AuditInteraction initialHistoryPage={localizedAuditHistoryPage} />
        <AuditSeoContent />
        <AuditFaqContent />
      </AppShell>
    </>
  );
}
