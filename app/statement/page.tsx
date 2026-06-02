import { AppShell, StatusChip } from "@/components/app-shell";
import { DeclarationPanels } from "@/components/ranking-dashboard";
import { pageMetadata } from "@/lib/seo";
import { getSiteData } from "@/lib/site-data";

export const dynamic = "force-dynamic";

export const metadata = pageMetadata({
  title: "排名口径与特别声明",
  description: "说明 AI 中转站排名的数据来源、评分权重、Codex 倍率口径、工作时段划分和使用风险提示。",
  pathname: "/statement",
});

export default async function StatementPage() {
  const siteData = await getSiteData();
  const generatedAtLabel = siteData.generatedAt.replace(/\s+[+-]\d{4}$/, "").trim() || "未知";

  return (
    <AppShell
      active="statement"
      data={siteData}
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
            <h1 className="section-title">{siteData.declaration.title}</h1>
            <p className="section-desc">{siteData.declaration.subtitle}</p>
          </div>
        </div>
        <div className="section-body">
          <DeclarationPanels data={siteData} />
        </div>
      </section>
    </AppShell>
  );
}
