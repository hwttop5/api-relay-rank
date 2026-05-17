import { AppShell, StatusChip } from "@/components/app-shell";
import { DeclarationPanels } from "@/components/ranking-dashboard";
import { getSiteData } from "@/lib/site-data";

export const dynamic = "force-dynamic";

export default async function StatementPage() {
  const siteData = await getSiteData();

  return (
    <AppShell
      active="statement"
      data={siteData}
      actions={
        <>
          <StatusChip label={`采集时间 ${siteData.generatedAt || "未知"}`} tone="accent" />
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
