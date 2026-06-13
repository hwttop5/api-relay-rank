import type {
  StationSubmissionAttachmentKind,
  StationSubmissionPaymentType,
  StationSubmissionPlatform,
} from "./types";

export const STATION_SUBMISSION_PAYMENT_TYPES: Array<{ value: StationSubmissionPaymentType; label: string; description: string }> = [
  { value: "subscription", label: "包月型（日卡、周卡、月卡）", description: "按时间包或周期额度出售。" },
  { value: "non_subscription", label: "非包月型（余额消费）", description: "充值余额后按用量扣费。" },
  { value: "mixed", label: "混合型", description: "同时提供包月/包日和余额消费。" },
  { value: "charity", label: "公益站（免费）", description: "不以付费充值为主要使用方式。" },
];

export const STATION_SUBMISSION_PLATFORMS: Array<{ value: StationSubmissionPlatform; label: string }> = [
  { value: "new_api", label: "new-api" },
  { value: "sub2api", label: "sub2api" },
  { value: "other", label: "其他" },
];

export const STATION_SUBMISSION_ATTACHMENT_KINDS: Array<{ value: StationSubmissionAttachmentKind; label: string }> = [
  { value: "group_multiplier", label: "分组倍率截图" },
  { value: "recharge_multiplier", label: "充值倍率截图" },
];

const PAYMENT_TYPE_VALUES = new Set(STATION_SUBMISSION_PAYMENT_TYPES.map((item) => item.value));
const PLATFORM_VALUES = new Set(STATION_SUBMISSION_PLATFORMS.map((item) => item.value));
const ATTACHMENT_KIND_VALUES = new Set(STATION_SUBMISSION_ATTACHMENT_KINDS.map((item) => item.value));

export function normalizeSubmissionPaymentType(value: unknown): StationSubmissionPaymentType | null {
  const text = String(value || "").trim();
  return PAYMENT_TYPE_VALUES.has(text as StationSubmissionPaymentType) ? (text as StationSubmissionPaymentType) : null;
}

export function normalizeSubmissionPlatform(value: unknown): StationSubmissionPlatform | null {
  const text = String(value || "").trim();
  return PLATFORM_VALUES.has(text as StationSubmissionPlatform) ? (text as StationSubmissionPlatform) : null;
}

export function normalizeSubmissionAttachmentKind(value: unknown): StationSubmissionAttachmentKind | null {
  const text = String(value || "").trim();
  return ATTACHMENT_KIND_VALUES.has(text as StationSubmissionAttachmentKind) ? (text as StationSubmissionAttachmentKind) : null;
}

export function submissionPaymentTypeLabel(value: StationSubmissionPaymentType | string) {
  return STATION_SUBMISSION_PAYMENT_TYPES.find((item) => item.value === value)?.label ?? String(value || "");
}

export function submissionPlatformLabel(value: StationSubmissionPlatform | string) {
  return STATION_SUBMISSION_PLATFORMS.find((item) => item.value === value)?.label ?? String(value || "");
}

export function submissionAttachmentKindLabel(value: StationSubmissionAttachmentKind | string) {
  return STATION_SUBMISSION_ATTACHMENT_KINDS.find((item) => item.value === value)?.label ?? String(value || "");
}

export function maskTestApiKey(value: unknown) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const prefix = text.slice(0, Math.min(4, text.length));
  const suffix = text.length > 8 ? text.slice(-4) : "";
  const hiddenLength = Math.max(4, text.length - prefix.length - suffix.length);
  return suffix ? `${prefix}${"*".repeat(hiddenLength)}${suffix}` : `${prefix}${"*".repeat(hiddenLength)}`;
}
