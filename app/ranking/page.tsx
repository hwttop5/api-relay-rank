import { RankingDashboard } from "@/components/ranking-dashboard";
import { absoluteUrl, pageMetadata, safeJsonLd, topRankingRows } from "@/lib/seo";
import { getSiteData } from "@/lib/site-data";

const PAGE_TITLE = "AI 中转站综合排名";
const PAGE_DESCRIPTION = "查看 AI 中转站正式综合排名、Codex 采用倍率、正确率、响应时间、请求样本和未纳入正式排名的收录站点。";

export const dynamic = "force-dynamic";

export const metadata = pageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  pathname: "/ranking",
});

export default async function RankingPage() {
  const siteData = await getSiteData();
  const itemListJsonLd = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: PAGE_TITLE,
    description: PAGE_DESCRIPTION,
    url: absoluteUrl("/ranking"),
    numberOfItems: topRankingRows(siteData).length,
    itemListElement: topRankingRows(siteData).map((row, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: row.label,
      url: absoluteUrl(`/stations/${encodeURIComponent(row.station)}`),
    })),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(itemListJsonLd) }} />
      <RankingDashboard data={siteData} />
    </>
  );
}
