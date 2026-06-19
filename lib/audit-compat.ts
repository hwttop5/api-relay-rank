import type { StationAuditDetectorResult, StationAuditHistoryItem, StationAuditSummary } from "./types";

export type AuditModelFamily = "anthropic" | "openai" | "gemini" | "unknown";

const LEGACY_CLAUDE_FALSE_POSITIVE =
  /(?:^|;\s*)Stream's message_start\.message\.model = '[^']+' does not contain 'claude'\s*[-\u2013\u2014\u2015\u2026\uFF0D\uFE58\uFE63\uFFFD?]*\s*relay may be routing to a substitute model/gi;

export function auditModelFamily(model: string): AuditModelFamily {
  const normalized = model.trim().toLowerCase().replace(/^models\//, "");
  if (!normalized) {
    return "unknown";
  }
  if (normalized === "claude" || normalized.startsWith("claude-")) {
    return "anthropic";
  }
  if (
    normalized.startsWith("gpt-") ||
    normalized.startsWith("chatgpt-") ||
    /^o[1345](?:-|$)/.test(normalized) ||
    normalized.startsWith("codex-") ||
    normalized.startsWith("computer-use-") ||
    normalized.startsWith("text-") ||
    normalized.startsWith("davinci") ||
    normalized.startsWith("babbage")
  ) {
    return "openai";
  }
  if (normalized.startsWith("gemini-")) {
    return "gemini";
  }
  return "unknown";
}

function cleanLegacyClaudeStreamFalsePositiveText(value: string, model: string) {
  if (!value || auditModelFamily(model) !== "openai") {
    return value;
  }
  const normalized = value.replace(/non-Claude stream model name/gi, "unexpected stream model family/name");
  if (!normalized.toLowerCase().includes("does not contain 'claude'")) {
    return normalized.trim();
  }
  return normalized
    .replace(LEGACY_CLAUDE_FALSE_POSITIVE, "")
    .replace(/\s*;\s*([.;])/g, "$1")
    .replace(/:\s*;/g, ":")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function cleanLegacyStreamModelCell(value: string, model: string) {
  if (auditModelFamily(model) !== "openai") {
    return value;
  }
  return value.replace(/\(NOT claude\)/gi, "(matches OpenAI/GPT)");
}

function hasRealStreamAnomaly(value: string) {
  return /input_tokens|output_tokens|usage rewrite|unknown sse|non-monotonic|signature_delta|empty signature/i.test(value);
}

export function cleanLegacyAuditReportMarkdown(body: string, model: string): string {
  if (auditModelFamily(model) !== "openai") {
    return body;
  }
  return body
    .split(/\r?\n/)
    .flatMap((rawLine) => {
      if (/^\s*-\s*Stream's message_start\.message\.model\b/i.test(rawLine) && /does not contain 'claude'/i.test(rawLine)) {
        return [];
      }
      let line = cleanLegacyClaudeStreamFalsePositiveText(rawLine, model);
      line = cleanLegacyStreamModelCell(line, model);
      if (/Stream integrity anomaly detected/i.test(line) && /does not contain 'claude'/i.test(rawLine) && !hasRealStreamAnomaly(line)) {
        return [];
      }
      return [line];
    })
    .join("\n");
}

function cleanTextList(values: string[] | undefined, model: string) {
  return values?.map((value) => cleanLegacyClaudeStreamFalsePositiveText(value, model)).filter(Boolean);
}

function cleanDetector(detector: StationAuditDetectorResult, model: string): StationAuditDetectorResult | null {
  if (auditModelFamily(model) !== "openai") {
    return detector;
  }
  const evidence = cleanTextList(detector.evidence, model);
  const summary = cleanLegacyClaudeStreamFalsePositiveText(detector.summary, model);
  if (
    detector.key === "stream_protocol" &&
    detector.status === "fail" &&
    detector.severity === "critical" &&
    !summary &&
    (!evidence || evidence.length === 0)
  ) {
    return null;
  }
  return {
    ...detector,
    summary: summary || detector.summary,
    evidence,
  };
}

export function cleanLegacyAuditSummary<T extends StationAuditSummary>(summary: T): T {
  if (auditModelFamily(summary.model) !== "openai") {
    return summary;
  }
  const detectorResults = summary.detectorResults
    ?.map((detector) => cleanDetector(detector, summary.model))
    .filter((detector): detector is StationAuditDetectorResult => Boolean(detector));
  const criticalFindings = cleanTextList(summary.criticalFindings, summary.model);
  const protocolVerdict =
    summary.protocolVerdict === "fail" &&
    detectorResults?.some((detector) => detector.key === "stream_protocol" && detector.status === "fail") === false
      ? "pass"
      : summary.protocolVerdict;

  return {
    ...summary,
    overallSummary: cleanLegacyClaudeStreamFalsePositiveText(summary.overallSummary, summary.model),
    auditVerdictReason: summary.auditVerdictReason
      ? cleanLegacyClaudeStreamFalsePositiveText(summary.auditVerdictReason, summary.model)
      : summary.auditVerdictReason,
    highlights: cleanTextList(summary.highlights, summary.model) ?? [],
    stepSummaries: summary.stepSummaries
      .map((step) => ({
        title: step.title,
        summary: cleanLegacyClaudeStreamFalsePositiveText(step.summary, summary.model),
      }))
      .filter((step) => step.summary),
    detectorResults,
    criticalFindings,
    protocolVerdict,
  };
}

export function cleanLegacyAuditHistoryItem<T extends StationAuditHistoryItem>(item: T): T {
  return cleanLegacyAuditSummary(item);
}
