import { AppShell, StatusChip } from "@/components/app-shell";
import { HomeAuditLauncher } from "@/components/home-audit-launcher";
import { getSiteData } from "@/lib/site-data";

export const dynamic = "force-dynamic";

export default async function AuditPage() {
  const siteData = await getSiteData();

  return (
    <AppShell
      active="audit"
      data={siteData}
      actions={
        <>
          <StatusChip label={`收录站点 ${siteData.stations.length}`} tone="accent" />
          <StatusChip label="主动黑盒审计" tone="blue" />
        </>
      }
    >
      <HomeAuditLauncher />
    </AppShell>
  );
}
