import { RankingDashboard } from "@/components/ranking-dashboard";
import { getSiteData } from "@/lib/site-data";

export const dynamic = "force-dynamic";

export default async function RankingPage() {
  const siteData = await getSiteData();
  return <RankingDashboard data={siteData} />;
}
