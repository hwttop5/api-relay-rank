export type TimeWindow = "work_hours" | "off_hours" | "all_hours";
export type SortMode = "composite" | "correct_rate" | "avg_seconds" | "effective_multiplier";
export type StationType = "subscription" | "non_subscription" | "mixed" | "unknown_pending";

export interface DeclarationPayload {
  title: string;
  subtitle: string;
  items: string[];
  environment: string;
  formula: string;
  adoptedMultiplierRule: string;
  scoring: string;
}

export interface RankingRow {
  rank: number;
  rankingBasis: string;
  timeWindow: TimeWindow;
  timeWindowLabel: string;
  station: string;
  label: string;
  stationUrl: string;
  stationType: StationType;
  stationTypeLabel: string;
  stationTypeShortLabel: string;
  totalScore: number;
  successScore: number;
  latencyScore: number;
  costScore: number;
  correctRate: number;
  avgSeconds: number;
  medianSeconds: number | null;
  p95Seconds: number | null;
  effectiveMultiplier: number;
  feeVerified: boolean;
  adoptedTier: string;
  adoptedGroup: string;
  adoptedRechargeName: string;
  billingType: string;
  billingTypeLabel: string;
  multiplierFullUseAssumption: string;
  requests: number;
  correct: number;
  failures: number;
  http2xx: number;
  http200WithError: number;
  firstAt: string;
  lastAt: string;
}

export interface QualityRow {
  station: string;
  label: string;
  platformGuess: string;
  timeWindow: TimeWindow;
  timeWindowLabel: string;
  requestSamples: number;
  correct: number;
  failures: number;
  correctRate: number;
  http2xx: number;
  http200WithError: number;
  nonnullError: number;
  excludedBillingErrors: number;
  avgSeconds: number | null;
  medianSeconds: number | null;
  p95Seconds: number | null;
  avgFirstResponseSeconds: number | null;
  firstAt: string;
  lastAt: string;
}

export interface GroupMultiplierRow {
  groupName: string;
  groupMultiplier: number;
}

export interface RechargeTierRow {
  rechargeName: string;
  billingType: string;
  billingTypeLabel: string;
  rmbAmount: number | null;
  usdAmount: number | null;
  rechargeLocation: string;
  expiresRule: string;
}

export interface AnnouncementRow {
  id: string;
  publishedAt: string;
  type: string;
  extra: string;
  content: string;
  sourceUrl: string;
}

export interface StationRecord {
  key: string;
  label: string;
  url: string;
  stationType: StationType;
  stationTypeLabel: string;
  stationTypeShortLabel: string;
  platformGuess: string;
  verifiedTierCount: number;
  groupMultipliers: GroupMultiplierRow[];
  rechargeTiers: RechargeTierRow[];
  tierNotes: string[];
  announcements: AnnouncementRow[];
  rankings: Partial<Record<TimeWindow, RankingRow>>;
  quality: Partial<Record<TimeWindow, QualityRow>>;
}

export interface SiteData {
  siteName: string;
  projectName: string;
  generatedAt: string;
  timezone: string;
  defaultTimeWindow: TimeWindow;
  defaultSort: SortMode;
  declaration: DeclarationPayload;
  timeWindows: Record<TimeWindow, { key: TimeWindow; label: string; range: string }>;
  rankings: Record<TimeWindow, RankingRow[]>;
  stations: StationRecord[];
  rankedStationCount: Record<TimeWindow, number>;
}
