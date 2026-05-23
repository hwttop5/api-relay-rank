import { readFile } from "node:fs/promises";
import { notFound } from "next/navigation";

import { SITE_DATA_PATH } from "./runtime-paths";
import type { SiteData, StationRecord } from "./types";

export async function getSiteData(): Promise<SiteData> {
  const raw = await readFile(SITE_DATA_PATH, "utf8");
  return JSON.parse(raw) as SiteData;
}

export async function getStationRecord(slug: string): Promise<{ siteData: SiteData; station: StationRecord }> {
  const siteData = await getSiteData();
  const station = siteData.stations.find((item) => item.key === slug);
  if (!station) {
    notFound();
  }
  return { siteData, station };
}
