import { formatMultiplier } from "./format";
import type { AuditVerdict, RankingDisplayRow, RankingPageData, RankingStationRecord, ShellData, SiteData, StatementPageData, TimeWindow } from "./types";
import type { StationReviewSummary } from "./types";

type StationRecord = SiteData["stations"][number];
type RegistryEvidenceKey = "groupMultipliers" | "rechargeTiers" | "announcements";

const CONFIRMED_EMPTY_EVIDENCE_STATUSES = new Set(["captured", "empty"]);
const MANUAL_FEE_REVIEW_STATIONS = new Set(["voapi"]);
const NON_CODEX_GROUP_KEYWORDS = [
  "claude",
  "anthropic",
  "sonnet",
  "opus",
  "haiku",
  "kiro",
  "windsurf",
  "bedrock",
  "cc-",
  "madeinchina",
  "国产",
  "公益",
  "deepseek",
  "qwen",
  "glm",
  "kimi",
  "doubao",
  "minimax",
] as const;
const WELFARE_GROUP_KEYWORDS = ["福利"] as const;
const IMAGE_ONLY_GROUP_KEYWORDS = ["gpt-image", "image", "img", "生图", "图片", "图像", "画图", "绘图"] as const;

function toShellData(siteData: SiteData, stationCount?: number): ShellData {
  return {
    siteName: siteData.siteName,
    projectName: siteData.projectName,
    generatedAt: siteData.generatedAt,
    stationCount,
  };
}

function getSampleCount(station: StationRecord, window: TimeWindow) {
  return station.quality[window]?.requestSamples ?? null;
}

function getTotalSampleCount(station: StationRecord) {
  return (getSampleCount(station, "work_hours") ?? 0) + (getSampleCount(station, "off_hours") ?? 0);
}

function getEvidenceStatus(station: StationRecord, key: RegistryEvidenceKey) {
  return station.dataEvidence?.find((item) => item.key === key)?.status;
}

function hasConfirmedEvidence(station: StationRecord, key: RegistryEvidenceKey) {
  const status = getEvidenceStatus(station, key);
  return status ? CONFIRMED_EMPTY_EVIDENCE_STATUSES.has(status) : false;
}

function formatStoredCount(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "-";
}

function hasVerifiedTierDisplayBasis(station: StationRecord) {
  return (
    station.groupMultipliers.length > 0 ||
    station.rechargeTiers.length > 0 ||
    hasConfirmedEvidence(station, "groupMultipliers") ||
    hasConfirmedEvidence(station, "rechargeTiers")
  );
}

function formatRegistryVerifiedTierCount(station: StationRecord) {
  if (Number.isFinite(station.verifiedTierCount) && station.verifiedTierCount > 0) {
    return String(station.verifiedTierCount);
  }
  return hasVerifiedTierDisplayBasis(station) ? "0" : "-";
}

function formatRegistryAnnouncementCount(station: StationRecord) {
  if (station.announcements.length > 0) {
    return String(station.announcements.length);
  }
  return hasConfirmedEvidence(station, "announcements") ? "0" : "-";
}

function isCodexLikeGroup(group: StationRecord["groupMultipliers"][number]) {
  const normalized = group.groupName.trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  if (WELFARE_GROUP_KEYWORDS.some((keyword) => normalized.includes(keyword))) {
    return false;
  }
  if (group.codexEligible === false) {
    return false;
  }
  if (group.codexEligible === true) {
    return true;
  }
  if (IMAGE_ONLY_GROUP_KEYWORDS.some((keyword) => normalized.includes(keyword))) {
    return false;
  }
  return !NON_CODEX_GROUP_KEYWORDS.some((keyword) => normalized.includes(keyword));
}

function getLowestUnrankedMultiplier(station: StationRecord) {
  const codexGroupMultipliers = station.groupMultipliers
    .filter((group) => isCodexLikeGroup(group))
    .map((group) => group.groupMultiplier)
    .filter((multiplier) => Number.isFinite(multiplier) && multiplier > 0);

  if (!codexGroupMultipliers.length) {
    return null;
  }

  const lowestGroupMultiplier = Math.min(...codexGroupMultipliers);
  const effectiveMultipliers: number[] = [];

  for (const tier of station.rechargeTiers) {
    const rmbAmount = tier.rmbAmount;
    const usdAmount = tier.usdAmount;
    if (
      rmbAmount === null ||
      usdAmount === null ||
      !Number.isFinite(rmbAmount) ||
      !Number.isFinite(usdAmount) ||
      usdAmount <= 0
    ) {
      continue;
    }

    const effectiveMultiplier = lowestGroupMultiplier * rmbAmount / usdAmount;
    if (Number.isFinite(effectiveMultiplier) && effectiveMultiplier > 0) {
      effectiveMultipliers.push(effectiveMultiplier);
    }
  }

  return effectiveMultipliers.length ? Math.min(...effectiveMultipliers) : null;
}

function needsManualFeeReview(station: StationRecord) {
  return station.verifiedTierCount <= 0 && (
    MANUAL_FEE_REVIEW_STATIONS.has(station.key) ||
    station.tierNotes.some((note) => note.includes("费用待人工复核") || note.includes("待人工复核"))
  );
}

function getUnrankedReason(station: StationRecord) {
  const hasGroupEvidence = station.groupMultipliers.length > 0;
  const hasRechargeEvidence = station.rechargeTiers.length > 0;
  const totalSamples = getTotalSampleCount(station);

  if (!hasGroupEvidence && !hasRechargeEvidence) {
    return "缺分组/充值证据";
  }
  if (!hasGroupEvidence) {
    return "缺分组证据";
  }
  if (!hasRechargeEvidence) {
    return "缺充值证据";
  }
  if (needsManualFeeReview(station)) {
    return "费用待人工复核";
  }
  if (station.verifiedTierCount <= 0) {
    return "缺正式费用行";
  }
  if (totalSamples <= 0) {
    return "缺请求样本";
  }
  return "费用待人工复核";
}

function getRegistryDisplayValues(station: StationRecord) {
  const lowestMultiplier = getLowestUnrankedMultiplier(station);
  const values = {
    lowestMultiplier: lowestMultiplier === null ? "-" : formatMultiplier(lowestMultiplier),
    sampleCount: formatStoredCount(station.quality.all_hours?.requestSamples),
    verifiedTierCount: formatRegistryVerifiedTierCount(station),
    announcementCount: formatRegistryAnnouncementCount(station),
  };

  return {
    ...values,
    hasData: Object.values(values).some((value) => value !== "-"),
  };
}

function getLatestAuditDisplay(station: StationRecord | undefined): { auditVerdict: AuditVerdict | null; auditScore: number | null } {
  const latestAudit = station?.audits?.latestByModel[0];
  return {
    auditVerdict: latestAudit?.overallVerdict ?? null,
    auditScore: typeof latestAudit?.auditScore === "number" && Number.isFinite(latestAudit.auditScore) ? latestAudit.auditScore : null,
  };
}

function toRankingDisplayRow(row: SiteData["rankings"][TimeWindow][number], station: StationRecord | undefined, reviewSummary?: StationReviewSummary): RankingDisplayRow {
  const latestAudit = getLatestAuditDisplay(station);
  return {
    rank: row.rank,
    station: row.station,
    label: row.label,
    stationUrl: row.stationUrl,
    stationType: row.stationType,
    stationTypeShortLabel: row.stationTypeShortLabel,
    auditVerdict: latestAudit.auditVerdict,
    auditScore: latestAudit.auditScore,
    totalScore: row.totalScore,
    correctRate: row.correctRate,
    avgSeconds: row.avgSeconds,
    effectiveMultiplier: row.effectiveMultiplier,
    adoptedTier: row.adoptedTier,
    reviewAverageRating: reviewSummary?.averageRating ?? null,
    reviewCount: reviewSummary?.reviewCount ?? 0,
    requests: row.requests,
  };
}

function toRankingStationRecord(station: StationRecord, reviewSummary?: StationReviewSummary): RankingStationRecord {
  const registryDisplay = getRegistryDisplayValues(station);
  const latestAudit = getLatestAuditDisplay(station);
  return {
    key: station.key,
    label: station.label,
    stationExternalUrl: station.inviteUrl || station.url,
    stationType: station.stationType,
    stationTypeLabel: station.stationTypeLabel,
    stationTypeShortLabel: station.stationTypeShortLabel,
    platformGuess: station.platformGuess,
    auditVerdict: latestAudit.auditVerdict,
    auditScore: latestAudit.auditScore,
    reviewAverageRating: reviewSummary?.averageRating ?? null,
    reviewCount: reviewSummary?.reviewCount ?? 0,
    unrankedReason: getUnrankedReason(station),
    registryDisplay,
  };
}

export function buildRankingPageData(siteData: SiteData, reviewSummaries: Record<string, StationReviewSummary> = {}): { shell: ShellData; data: RankingPageData } {
  const shell = toShellData(siteData, siteData.stations.length);
  const stationMap = new Map(siteData.stations.map((station) => [station.key, station]));
  return {
    shell,
    data: {
      ...shell,
      defaultTimeWindow: siteData.defaultTimeWindow,
      defaultSort: siteData.defaultSort,
      timeWindows: siteData.timeWindows,
      rankings: {
        all_hours: siteData.rankings.all_hours.map((row) => toRankingDisplayRow(row, stationMap.get(row.station), reviewSummaries[row.station])),
        work_hours: siteData.rankings.work_hours.map((row) => toRankingDisplayRow(row, stationMap.get(row.station), reviewSummaries[row.station])),
        off_hours: siteData.rankings.off_hours.map((row) => toRankingDisplayRow(row, stationMap.get(row.station), reviewSummaries[row.station])),
      },
      stations: siteData.stations.map((station) => toRankingStationRecord(station, reviewSummaries[station.key])),
      rankedStationCount: siteData.rankedStationCount,
    },
  };
}

export function buildStatementPageData(siteData: SiteData): { shell: ShellData; data: StatementPageData } {
  const shell = toShellData(siteData, siteData.stations.length);
  return {
    shell,
    data: {
      ...shell,
      declaration: siteData.declaration,
    },
  };
}

export function buildShellData(siteData: SiteData, stationCount?: number): ShellData {
  return toShellData(siteData, stationCount);
}
