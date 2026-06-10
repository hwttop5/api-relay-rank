import { AppShell, StatusChip } from "@/components/app-shell";
import { DeclarationPanels } from "@/components/declaration-panels";
import { absoluteUrl, pageMetadata, safeJsonLd } from "@/lib/seo";
import { getSiteData } from "@/lib/site-data";
import { buildStatementPageData } from "@/lib/site-data-view";

export const revalidate = 300;

const PAGE_TITLE = "排名口径与特别声明";
const PAGE_DESCRIPTION = "说明 AI 中转站排名的数据来源、评分权重、Codex 倍率口径、工作时段划分和使用风险提示。";

export const metadata = pageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  pathname: "/statement",
});

export default async function StatementPage() {
  const siteData = await getSiteData();
  const statementPage = buildStatementPageData(siteData);
  const generatedAtLabel = statementPage.data.generatedAt.replace(/\s+[+-]\d{4}$/, "").trim() || "未知";
  const webPageJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: PAGE_TITLE,
    description: PAGE_DESCRIPTION,
    url: absoluteUrl("/statement"),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(webPageJsonLd) }} />
      <AppShell
        active="statement"
        data={statementPage.shell}
        topbarMetaClassName="topbar-meta-inline-mobile"
        actions={
          <>
            <StatusChip label={`采集时间 ${generatedAtLabel}`} tone="accent" />
            <StatusChip label="排名口径说明" tone="warn" />
          </>
        }
      >
        <section className="section declaration-section">
          <div className="section-head ranking-head">
            <div>
              <h1 className="section-title">{statementPage.data.declaration.title}</h1>
              <p className="section-desc">{statementPage.data.declaration.subtitle}</p>
            </div>
          </div>
          <div className="section-body">
            <DeclarationPanels data={statementPage.data} />
          </div>
        </section>
      </AppShell>
    </>
  );
}
