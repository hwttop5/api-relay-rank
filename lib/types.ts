export type TimeWindow = "work_hours" | "off_hours" | "all_hours";
export type SortMode = "composite" | "correct_rate" | "avg_seconds" | "effective_multiplier" | "review_rating";
export type StationType = "subscription" | "non_subscription" | "mixed" | "charity" | "unknown_pending";
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
  displayOnly?: boolean;
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
  contentHtml?: string;
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

export interface StationAuditDetectorResult {
  key: string;
  label: string;
  category: "security" | "protocol" | "capability" | "authenticity" | "long_context" | string;
  status: "pass" | "warn" | "fail" | "skip" | "error" | string;
  score?: number;
  weight?: number;
  severity?: "info" | "medium" | "high" | "critical" | string;
  summary: string;
  evidence?: string[];
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
  auditScore?: number;
  auditVerdictReason?: string;
  capabilityVerdict?: string;
  protocolVerdict?: string;
  authenticityVerdict?: string;
  longContextVerdict?: string;
  detectorResults?: StationAuditDetectorResult[];
  criticalFindings?: string[];
  runMode?: string;
  costNotice?: string;
}

export interface StationAuditHistoryItem extends StationAuditSummary {
  stationKey: string;
  stationLabel: string;
  stationUrl: string;
  runId: string;
  reportUrl: string;
}

export type AuditHistoryTimeRange = "all" | "24h" | "7d" | "30d" | "90d";
export type AuditHistorySortKey = "executedAt" | "station" | "model" | "verdict" | "score";
export type AuditHistorySortDirection = "asc" | "desc";

export interface AuditHistoryFilters {
  station: string;
  model: string;
  verdict: "all" | AuditVerdict;
  timeRange: AuditHistoryTimeRange;
  sort: AuditHistorySortKey;
  direction: AuditHistorySortDirection;
  page: number;
  pageSize: number;
}

export interface AuditHistoryFilterOption {
  value: string;
  label: string;
}

export interface AuditHistoryFilterOptions {
  stations: AuditHistoryFilterOption[];
  models: AuditHistoryFilterOption[];
}

export interface AuditHistoryPage {
  items: StationAuditHistoryItem[];
  total: number;
  page: number;
  pageSize: number;
  pageCount: number;
  filters: AuditHistoryFilters;
  options: AuditHistoryFilterOptions;
}

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
  inviteUrl?: string;
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

export interface ShellData {
  siteName: string;
  projectName: string;
  generatedAt: string;
  stationCount?: number;
}

export interface RankingDisplayRow {
  rank: number;
  station: string;
  label: string;
  stationUrl: string;
  stationType: StationType;
  stationTypeShortLabel: string;
  totalScore: number;
  correctRate: number;
  avgSeconds: number;
  effectiveMultiplier: number;
  adoptedTier: string;
  reviewAverageRating: number | null;
  reviewCount: number;
  requests: number;
}

export interface RankingStationRecord {
  key: string;
  label: string;
  stationExternalUrl: string;
  stationType: StationType;
  stationTypeLabel: string;
  stationTypeShortLabel: string;
  platformGuess: string;
  reviewAverageRating: number | null;
  reviewCount: number;
  unrankedReason: string;
  registryDisplay: {
    lowestMultiplier: string;
    sampleCount: string;
    verifiedTierCount: string;
    announcementCount: string;
    hasData: boolean;
  };
}

export interface RankingPageData extends ShellData {
  defaultTimeWindow: TimeWindow;
  defaultSort: SortMode;
  timeWindows: Record<TimeWindow, { key: TimeWindow; label: string; range: string }>;
  rankings: Record<TimeWindow, RankingDisplayRow[]>;
  stations: RankingStationRecord[];
  rankedStationCount: Record<TimeWindow, number>;
}

export interface StatementPageData extends ShellData {
  declaration: DeclarationPayload;
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

export interface PageViewStats {
  totalPv: number;
  stationPv: Record<string, number>;
}

export interface AuthenticatedGithubUser {
  githubId: string;
  githubLogin: string;
  name: string | null;
  avatarUrl: string | null;
  profileUrl: string | null;
}

export interface StationReviewSummary {
  station: string;
  averageRating: number | null;
  reviewCount: number;
}

export interface StationReviewItem {
  id: number;
  station: string;
  rating: number;
  comment: string;
  githubLogin: string;
  githubAvatarUrl: string | null;
  githubProfileUrl: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ViewerReview {
  rating: number;
  comment: string;
  createdAt: string;
  updatedAt: string;
}

export interface StationReviewPagination {
  limit: number;
  offset: number;
  nextOffset: number | null;
  hasMore: boolean;
}

export interface StationReviewPage {
  summary: StationReviewSummary;
  reviews: StationReviewItem[];
  pagination: StationReviewPagination;
  viewer: AuthenticatedGithubUser | null;
  viewerReview: ViewerReview | null;
}

export type StationErrorReportCategory =
  | "station_url"
  | "group_multiplier"
  | "recharge_tier"
  | "announcement"
  | "ranking_metric"
  | "other";
