import { readFile } from "node:fs/promises";
import path from "node:path";

import { hasDatabaseUrl, readPageViewStats } from "./postgres";
import { SITE_TOTAL_IMPORT_PATH, normalizePageViewPath } from "./page-view-path";
import type { PageViewStats } from "./types";

const PAGE_VIEW_BASELINES_PATH = path.join(process.cwd(), "config", "page_view_baselines.json");

function emptyStats(): PageViewStats {
  return {
    totalPv: 0,
    stationPv: {},
  };
}

function safeCount(value: unknown) {
  const number = typeof value === "number" ? value : Number(String(value ?? "").replace(/,/g, ""));
  return Number.isFinite(number) && number > 0 ? Math.trunc(number) : 0;
}

async function readBaselinePageViewStats(): Promise<PageViewStats> {
  let rows: unknown;
  try {
    rows = JSON.parse(await readFile(PAGE_VIEW_BASELINES_PATH, "utf8"));
  } catch {
    return emptyStats();
  }
  if (!Array.isArray(rows)) {
    return emptyStats();
  }

  const stats = emptyStats();
  const totalPeriods = new Set<string>();
  const pageRowsWithoutTotal: Array<{ periodKey: string; canonicalPath: string; stationKey: string | null; pvCount: number }> = [];

  for (const row of rows) {
    if (!row || typeof row !== "object") {
      continue;
    }
    const payload = row as Record<string, unknown>;
    const source = String(payload.source || "baidu");
    const periodStart = String(payload.periodStart || "");
    const periodEnd = String(payload.periodEnd || "");
    const periodKey = `${source}:${periodStart}:${periodEnd}`;
    const canonicalPath = String(payload.canonicalPath || "");
    const pvCount = safeCount(payload.pvCount);
    if (!periodStart || !periodEnd || pvCount <= 0) {
      continue;
    }

    if (canonicalPath === SITE_TOTAL_IMPORT_PATH) {
      totalPeriods.add(periodKey);
      stats.totalPv += pvCount;
      continue;
    }

    const normalized = normalizePageViewPath(canonicalPath);
    if (!normalized) {
      continue;
    }
    pageRowsWithoutTotal.push({
      periodKey,
      canonicalPath: normalized.canonicalPath,
      stationKey: normalized.stationKey,
      pvCount,
    });
  }

  for (const row of pageRowsWithoutTotal) {
    if (!totalPeriods.has(row.periodKey)) {
      stats.totalPv += row.pvCount;
    }
    if (row.stationKey) {
      stats.stationPv[row.stationKey] = (stats.stationPv[row.stationKey] ?? 0) + row.pvCount;
    }
  }

  return stats;
}

export async function getPageViewStats(): Promise<PageViewStats> {
  if (hasDatabaseUrl()) {
    try {
      return await readPageViewStats();
    } catch {
      return readBaselinePageViewStats();
    }
  }
  return readBaselinePageViewStats();
}
