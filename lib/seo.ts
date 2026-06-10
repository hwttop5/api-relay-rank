import type { Metadata } from "next";

import { formatMultiplier, formatPercent, formatScore } from "@/lib/format";
import type { RankingRow, SiteData, StationRecord } from "@/lib/types";

export const SITE_TITLE = "AI中转站监视者";
export const DEFAULT_DESCRIPTION = "api-relay-rank：查看 AI 中转站正式排名、Codex 倍率、响应质量、安全审计与公开公告。";
export const DEFAULT_SITE_BASE_URL = "https://apirank.ttop5.cc";
export const SITE_IMAGE_PATH = "/opengraph-image";
export const SITE_IMAGE_WIDTH = 1200;
export const SITE_IMAGE_HEIGHT = 630;

const LOCAL_BASE_URL = "http://localhost:3000";

function trimTrailingSlash(value: string) {
  return value.replace(/\/+$/, "");
}

function normalizeBaseUrl(value: string | undefined) {
  const raw = value?.trim();
  if (!raw) {
    return null;
  }

  try {
    const url = new URL(raw.startsWith("http") ? raw : `https://${raw}`);
    return trimTrailingSlash(url.origin);
  } catch {
    return null;
  }
}

export function getSiteBaseUrl() {
  return (
    normalizeBaseUrl(process.env.NEXT_PUBLIC_SITE_URL) ??
    normalizeBaseUrl(process.env.VERCEL_PROJECT_PRODUCTION_URL) ??
    normalizeBaseUrl(process.env.VERCEL_URL) ??
    normalizeBaseUrl(process.env.APP_DOMAIN) ??
    (process.env.NODE_ENV === "development" ? LOCAL_BASE_URL : DEFAULT_SITE_BASE_URL)
  );
}

export function absoluteUrl(pathname: string) {
  const path = pathname.startsWith("/") ? pathname : `/${pathname}`;
  return `${getSiteBaseUrl()}${path}`;
}

export function pageMetadata({
  title,
  description,
  pathname,
}: {
  title: string;
  description: string;
  pathname: string;
}): Metadata {
  return {
    title,
    description,
    alternates: {
      canonical: pathname,
    },
    openGraph: {
      title,
      description,
      url: pathname,
      siteName: SITE_TITLE,
      locale: "zh_CN",
      type: "website",
      images: [
        {
          url: SITE_IMAGE_PATH,
          width: SITE_IMAGE_WIDTH,
          height: SITE_IMAGE_HEIGHT,
          alt: SITE_TITLE,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [SITE_IMAGE_PATH],
    },
  };
}

export function topRankingRows(siteData: SiteData, count = 10) {
  return siteData.rankings.all_hours.slice(0, count);
}

export function findBestRanking(station: StationRecord): RankingRow | null {
  return station.rankings.all_hours ?? station.rankings.work_hours ?? station.rankings.off_hours ?? null;
}

export function stationMetadataDescription(station: StationRecord) {
  const ranking = findBestRanking(station);
  const rankingText = ranking
    ? `综合排名第 ${ranking.rank}，总分 ${formatScore(ranking.totalScore)}，正确率 ${formatPercent(ranking.correctRate)}，采用倍率 ${formatMultiplier(ranking.effectiveMultiplier)}。`
    : "当前暂无正式排名数据。";

  return `${station.label} 是 ${station.stationTypeShortLabel}，平台判断为 ${station.platformGuess || "未识别"}。${rankingText}页面汇总分组倍率、充值档位、安全审计和最新公告。`;
}

export function stationPageTitle(station: StationRecord) {
  return `${station.label} 中转站详情`;
}

export function safeJsonLd(value: unknown) {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}
