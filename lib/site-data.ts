import { readFile } from "node:fs/promises";
import path from "node:path";
import { notFound } from "next/navigation";

import type { SiteData, StationRecord } from "./types";

const DATA_PATH = path.join(process.cwd(), "data", "site-data.json");

export async function getSiteData(): Promise<SiteData> {
  const raw = await readFile(DATA_PATH, "utf8");
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
