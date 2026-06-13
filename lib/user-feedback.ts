import type { StationErrorReportCategory, StationReviewSummary } from "./types";

export const ERROR_REPORT_CATEGORIES: Array<{ value: StationErrorReportCategory; label: string }> = [
  { value: "station_url", label: "站点地址" },
  { value: "group_multiplier", label: "分组倍率" },
  { value: "recharge_tier", label: "充值档位" },
  { value: "announcement", label: "公告/站点信息" },
  { value: "ranking_metric", label: "排名指标" },
  { value: "other", label: "其他错误" },
];

const ERROR_REPORT_CATEGORY_VALUES = new Set(ERROR_REPORT_CATEGORIES.map((item) => item.value));

export const REVIEW_RATING_CHOICES = [
  { stars: 1, rating: 2, label: "很差" },
  { stars: 2, rating: 4, label: "较差" },
  { stars: 3, rating: 6, label: "还行" },
  { stars: 4, rating: 8, label: "推荐" },
  { stars: 5, rating: 10, label: "力荐" },
] as const;

const REVIEW_RATING_VALUES = new Set(REVIEW_RATING_CHOICES.map((choice) => choice.rating));

export function normalizeErrorReportCategory(value: unknown): StationErrorReportCategory | null {
  const text = String(value || "").trim();
  return ERROR_REPORT_CATEGORY_VALUES.has(text as StationErrorReportCategory) ? (text as StationErrorReportCategory) : null;
}

export function normalizeRating(value: unknown): number | null {
  const rating = typeof value === "number" ? value : Number(value);
  if (!Number.isInteger(rating) || !REVIEW_RATING_VALUES.has(rating as 2 | 4 | 6 | 8 | 10)) {
    return null;
  }
  return rating;
}

export function ratingToStars(value: number | null | undefined) {
  return REVIEW_RATING_CHOICES.find((choice) => choice.rating === value)?.stars ?? null;
}

export function starsToRating(value: number | null | undefined) {
  return REVIEW_RATING_CHOICES.find((choice) => choice.stars === value)?.rating ?? null;
}

export function ratingLabel(value: number | null | undefined) {
  return REVIEW_RATING_CHOICES.find((choice) => choice.rating === value)?.label ?? "";
}

export function normalizeReviewComment(value: unknown) {
  return String(value ?? "").trim().slice(0, 1000);
}

export function emptyReviewSummary(station: string): StationReviewSummary {
  return {
    station,
    averageRating: null,
    reviewCount: 0,
  };
}

export function formatReviewSummary(summary: StationReviewSummary, options: { includeCount?: boolean } = {}) {
  if (!summary.reviewCount || summary.averageRating === null) {
    return "暂无";
  }
  if (options.includeCount === false) {
    return `${summary.averageRating.toFixed(1)} 分`;
  }
  return `${summary.averageRating.toFixed(1)} 分 / ${summary.reviewCount} 条`;
}
