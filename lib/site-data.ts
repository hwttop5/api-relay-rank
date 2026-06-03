import { readFile } from "node:fs/promises";
import { notFound } from "next/navigation";

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
  if (siteDataSource() === "postgres" && hasDatabaseUrl()) {
    try {
      return await readLatestSiteDataSnapshot();
    } catch (error) {
      if (!allowFileFallback()) {
        throw error;
      }
    }
  }
  return readSiteDataFile();
}

export async function getStationRecord(slug: string): Promise<{ siteData: SiteData; station: StationRecord }> {
  const siteData = await getSiteData();
  const station = siteData.stations.find((item) => item.key === slug);
  if (!station) {
    notFound();
  }
  return { siteData, station };
}
