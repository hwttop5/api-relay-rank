import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile("lib/audit-compat.ts", "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { cleanLegacyAuditReportMarkdown, cleanLegacyAuditSummary } = await import(moduleUrl);

test("cleans legacy Claude false positive from GPT markdown and keeps usage rewrite", () => {
  const markdown = [
    "## Risk Summary",
    "- 🔴 Stream integrity anomaly detected (AC-1 SSE-level): input_tokens at message_start (0) disagrees with message_delta samples ([124]) — usage rewrite; Stream's message_start.message.model = 'gpt-5.5' does not contain 'claude' — relay may be routing to a substitute model",
    "",
    "## 10. Stream Integrity (AC-1 SSE-level)",
    "| Stream model | gpt-5.5 (NOT claude) |",
    "- input_tokens at message_start (0) disagrees with message_delta samples ([124]) — usage rewrite",
    "- Stream's message_start.message.model = 'gpt-5.5' does not contain 'claude' — relay may be routing to a substitute model",
  ].join("\n");

  const cleaned = cleanLegacyAuditReportMarkdown(markdown, "gpt-5.5");

  assert.doesNotMatch(cleaned, /NOT claude/i);
  assert.doesNotMatch(cleaned, /does not contain 'claude'/i);
  assert.match(cleaned, /usage rewrite/);
  assert.match(cleaned, /matches OpenAI\/GPT/);
});

test("does not clean Claude-family legacy mismatch summary", () => {
  const summary = {
    profile: "general",
    model: "claude-opus-4-7",
    auditedBaseUrl: "https://relay.example/v1",
    executedAt: "2026-01-02T00:00:00Z",
    overallVerdict: "high",
    overallSummary:
      "Stream integrity anomaly detected (AC-1 SSE-level): Stream's message_start.message.model = 'gpt-5.5' does not contain 'claude' — relay may be routing to a substitute model",
    highlights: [],
    stepSummaries: [],
    reportPath: "data/_audit_runs/demo/claude-opus/run/report.md",
    toolVersion: "api-relay-audit@test",
  };

  const cleaned = cleanLegacyAuditSummary(summary);

  assert.match(cleaned.overallSummary, /does not contain 'claude'/i);
});

test("cleans GPT summary fields without dropping real stream anomalies", () => {
  const summary = {
    profile: "general",
    model: "gpt-5.5",
    auditedBaseUrl: "https://relay.example/v1",
    executedAt: "2026-01-02T00:00:00Z",
    overallVerdict: "high",
    overallSummary:
      "Stream integrity anomaly detected (AC-1 SSE-level). The relay's streaming response fails one or more structural invariants: unknown SSE event types, non-monotonic usage fields, rewritten input_tokens, empty thinking signatures, or a non-Claude stream model name. Do not use.",
    highlights: [
      "🔴 Stream integrity anomaly detected (AC-1 SSE-level): input_tokens at message_start (0) disagrees with message_delta samples ([124]) — usage rewrite; Stream's message_start.message.model = 'gpt-5.5' does not contain 'claude' — relay may be routing to a substitute model",
    ],
    stepSummaries: [
      {
        title: "10. Stream Integrity (AC-1 SSE-level)",
        summary:
          "🔴 Stream integrity anomaly detected (AC-1 SSE-level): input_tokens at message_start (0) disagrees with message_delta samples ([124]) — usage rewrite; Stream's message_start.message.model = 'gpt-5.5' does not contain 'claude' — relay may be routing to a substitute model",
      },
    ],
    reportPath: "data/_audit_runs/demo/gpt-5.5/run/report.md",
    toolVersion: "api-relay-audit@test",
    protocolVerdict: "fail",
    detectorResults: [
      {
        key: "stream_protocol",
        label: "Stream protocol",
        category: "protocol",
        status: "fail",
        severity: "critical",
        summary: "Stream response violates usage invariants.",
        evidence: [
          "input_tokens at message_start (0) disagrees with message_delta samples ([124]) — usage rewrite; Stream's message_start.message.model = 'gpt-5.5' does not contain 'claude' — relay may be routing to a substitute model",
        ],
      },
    ],
    criticalFindings: [
      "Stream integrity anomaly detected (AC-1 SSE-level): input_tokens at message_start (0) disagrees with message_delta samples ([124]) — usage rewrite; Stream's message_start.message.model = 'gpt-5.5' does not contain 'claude' — relay may be routing to a substitute model",
    ],
  };

  const cleaned = cleanLegacyAuditSummary(summary);
  const serialized = JSON.stringify(cleaned);

  assert.doesNotMatch(serialized, /does not contain 'claude'/i);
  assert.doesNotMatch(serialized, /non-Claude stream model name/i);
  assert.match(serialized, /usage rewrite/);
  assert.equal(cleaned.protocolVerdict, "fail");
});

test("audit report, history, and localization call the compatibility layer", async () => {
  const [route, history, localization] = await Promise.all([
    readFile("app/api/audit-report/route.ts", "utf8"),
    readFile("lib/audit-history.ts", "utf8"),
    readFile("lib/audit-localization.ts", "utf8"),
  ]);

  assert.match(route, /cleanLegacyAuditReportMarkdown\(body, model\)/);
  assert.match(history, /cleanLegacyAuditSummary\(summary\)/);
  assert.match(localization, /cleanLegacyAuditSummary\(summary\)/);
});
