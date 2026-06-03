import type { MetadataRoute } from "next";

import { absoluteUrl } from "@/lib/seo";
import { getSiteData } from "@/lib/site-data";

function parseLastModified(value: string) {
  const normalized = value.replace(/ ([+-]\d{2})(\d{2})$/, "$1:$2");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const siteData = await getSiteData();
  const lastModified = parseLastModified(siteData.generatedAt);
  const staticRoutes: MetadataRoute.Sitemap = [
    {
      url: absoluteUrl("/ranking"),
      lastModified,
      changeFrequency: "daily",
      priority: 1,
    },
    {
      url: absoluteUrl("/audit"),
      lastModified,
      changeFrequency: "daily",
      priority: 0.8,
    },
    {
      url: absoluteUrl("/statement"),
      lastModified,
      changeFrequency: "weekly",
      priority: 0.7,
    },
  ];

  const stationRoutes: MetadataRoute.Sitemap = siteData.stations.map((station) => ({
    url: absoluteUrl(`/stations/${encodeURIComponent(station.key)}`),
    lastModified,
    changeFrequency: "daily",
    priority: station.rankings.all_hours || station.rankings.work_hours || station.rankings.off_hours ? 0.8 : 0.6,
  }));

  return [...staticRoutes, ...stationRoutes];
}
