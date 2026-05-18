import { AppShell, StatusChip } from "@/components/app-shell";
import { AuditHistoryTable } from "@/components/audit-history-table";
import { HomeAuditLauncher } from "@/components/home-audit-launcher";
import { getAuditHistory } from "@/lib/audit-history";
import { getSiteData } from "@/lib/site-data";

export const dynamic = "force-dynamic";

export default async function AuditPage() {
  const siteData = await getSiteData();
  const auditHistory = await getAuditHistory(siteData);

  return (
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
      <HomeAuditLauncher />
      <AuditHistoryTable history={auditHistory} />
    </AppShell>
  );
}
