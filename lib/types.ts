export type TimeWindow = "work_hours" | "off_hours" | "all_hours";
export type SortMode = "composite" | "correct_rate" | "avg_seconds" | "effective_multiplier";
export type StationType = "subscription" | "non_subscription" | "mixed" | "unknown_pending";
export type AuditProfile = "general";
export type AuditVerdict = "low" | "medium" | "high" | "inconclusive";

export interface DeclarationPayload {
  title: string;
  subtitle: string;
  conclusion?: string[];
  items: string[];
  environment: string;
  coreItems?: string[];
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
  codexEligible?: boolean;
  usageLabel?: string;
}

export interface RechargeTierRow {
  rechargeName: string;
  billingType: string;
  billingTypeLabel: string;
  rmbAmount: number | null;
  usdAmount: number | null;
  paymentCurrency?: string;
  paymentAmount?: number | null;
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

export interface DataEvidenceRow {
  key: "groupMultipliers" | "rechargeTiers" | "announcements" | "publicProbe";
  label: string;
  count: number;
  status: "captured" | "empty" | "failed" | "missing" | "login_required" | "blocked" | "public_missing";
  statusLabel: string;
  message: string;
  source: string;
}

export interface StationAuditStepSummary {
  title: string;
  summary: string;
}

export interface StationAuditSummary {
  profile: AuditProfile;
  model: string;
  auditedBaseUrl: string;
  executedAt: string;
  overallVerdict: AuditVerdict;
  overallSummary: string;
  highlights: string[];
  stepSummaries: StationAuditStepSummary[];
  reportPath: string;
  toolVersion: string;
  runStatus?: "success";
  durationMs?: number;
  engineCommit?: string;
  effectiveOptions?: Record<string, unknown>;
}

export interface StationAuditHistoryItem extends StationAuditSummary {
  stationKey: string;
  stationLabel: string;
  stationUrl: string;
  runId: string;
  reportUrl: string;
}

export type AuditHistoryTimeRange = "all" | "24h" | "7d" | "30d" | "90d";
export type AuditHistorySortKey = "executedAt" | "station" | "model" | "verdict";
export type AuditHistorySortDirection = "asc" | "desc";

export interface StationAudits {
  defaultModel: string;
  availableModels: string[];
  latestByModel: StationAuditSummary[];
  latestAuditAt: string | null;
}

export interface AuditModelOption {
  label: string;
  value: string;
  badge?: string;
}

export interface HomeAuditRunRequest {
  apiBaseUrl: string;
  apiKey: string;
  model: string;
}

export interface HomeAuditRunResponse {
  station: string;
  model: string;
  summary: StationAuditSummary;
  historyItem?: StationAuditHistoryItem;
  stationUrl: string;
  reportUrl: string;
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
  dataEvidence?: DataEvidenceRow[];
  rankings: Partial<Record<TimeWindow, RankingRow>>;
  quality: Partial<Record<TimeWindow, QualityRow>>;
  audits?: StationAudits;
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
