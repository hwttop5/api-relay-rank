import { AppShell, StatusChip } from "@/components/app-shell";
import { AuditInteraction } from "@/components/audit-interaction";
import { AUDIT_FAQ_ITEMS, AuditFaqContent, AuditSeoContent } from "@/components/audit-seo-content";
import { getAuditHistory } from "@/lib/audit-history";
import { localizeAuditHistoryItemText, localizeSiteDataAuditText } from "@/lib/audit-localization";
import { absoluteUrl, pageMetadata, safeJsonLd } from "@/lib/seo";
import { getSiteData } from "@/lib/site-data";

const PAGE_TITLE = "AI 中转站安全审计";
const PAGE_DESCRIPTION = "输入 AI 中转站 API 地址和临时 API Key，执行本地黑盒安全审计，查看风险等级、审计摘要和历史报告。";

export const dynamic = "force-dynamic";

export const metadata = pageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  pathname: "/audit",
});

export default async function AuditPage() {
  const rawSiteData = await getSiteData();
  const siteData = localizeSiteDataAuditText(rawSiteData);
  const auditHistory = (await getAuditHistory(rawSiteData)).map(localizeAuditHistoryItemText);
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
        data={siteData}
        topbarMetaClassName="topbar-meta-inline-mobile"
        actions={
          <>
            <StatusChip label={`收录站点 ${siteData.stations.length}`} tone="accent" />
            <StatusChip label={`历史记录 ${auditHistory.length}`} tone="warn" />
            <StatusChip label="主动黑盒审计" tone="blue" />
          </>
        }
      >
        <AuditInteraction history={auditHistory} />
        <AuditSeoContent />
        <AuditFaqContent />
      </AppShell>
    </>
  );
}
