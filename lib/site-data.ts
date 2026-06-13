import { readFile } from "node:fs/promises";
import { notFound } from "next/navigation";

import { rankingCache, stationCache } from "./cache";
import { hasDatabaseUrl, readLatestSiteDataSnapshot } from "./postgres";
import { SITE_DATA_PATH } from "./runtime-paths";
import type { SiteData, StationRecord } from "./types";

function siteDataSource() {
  return process.env.SITE_DATA_SOURCE?.trim().toLowerCase() || "json";
}

async function readSiteDataFile(): Promise<SiteData> {
  const raw = await readFile(SITE_DATA_PATH, "utf8");
  return JSON.parse(raw) as SiteData;
}

function allowFileFallback() {
  return process.env.SITE_DATA_ALLOW_FILE_FALLBACK === "1";
}

export async function getSiteData(): Promise<SiteData> {
  const cacheKey = "site-data-full";
  const cached = rankingCache.get(cacheKey) as SiteData | null;
  if (cached) {
    return cached;
  }

  let data: SiteData;
  if (siteDataSource() === "postgres" && hasDatabaseUrl()) {
    try {
      data = await readLatestSiteDataSnapshot();
    } catch (error) {
      if (!allowFileFallback()) {
        throw error;
      }
      data = await readSiteDataFile();
    }
  } else {
    data = await readSiteDataFile();
  }

  rankingCache.set(cacheKey, data);
  return data;
}

export async function getStationRecord(slug: string): Promise<{ siteData: SiteData; station: StationRecord }> {
  const cacheKey = `station-record-${slug}`;
  const cached = stationCache.get(cacheKey) as { siteData: SiteData; station: StationRecord } | null;
  if (cached) {
    return cached;
  }

  const siteData = await getSiteData();
  const station = siteData.stations.find((item) => item.key === slug);
  if (!station) {
    notFound();
  }

  const result = { siteData, station };
  stationCache.set(cacheKey, result);
  return result;
}
