import type { SiteData, StationAuditHistoryItem, StationAuditSummary, StationRecord } from "./types";

const EXACT_TRANSLATIONS: Record<string, string> = {
  "Stream integrity anomaly detected (AC-1 SSE-level). The relay's streaming response fails one or more structural invariants: unknown SSE event types, non-monotonic usage fields, rewritten input_tokens, empty thinking signatures, or a non-Claude stream model name. Do not use.":
    "检测到流式响应完整性异常（AC-1 SSE 层）。该中转站的流式响应不满足一个或多个结构性约束：出现未知 SSE 事件类型、usage 字段非单调、input_tokens 被改写、thinking 签名为空，或流式模型名不是 Claude。建议不要使用。",
  "Hidden injection detected but instructions may partially work. OK for simple Q&A, not recommended for complex applications.":
    "检测到隐藏提示词注入，但用户指令仍可能部分生效。简单问答可以勉强使用，不建议用于复杂应用或代理任务。",
  "Audit report did not contain a supported overall verdict section.": "审计报告未包含可识别的总体评级段落。",
  "No significant injection, instruction override, or leakage detected.": "未检测到明显提示词注入、指令覆盖或信息泄漏。",
  "No summary extracted.": "未提取到摘要。",

  "Hidden system prompt injection detected (~105 tokens/request)": "检测到隐藏系统提示词注入（约 105 tokens/请求）",
  "Test A - Verbatim: Hidden prompt content extracted!": "测试 A - 原文复述：已提取出隐藏提示词内容！",
  "Test C - JSON continuation: Hidden prompt content extracted!": "测试 C - JSON 续写：已提取出隐藏提示词内容！",
  "Cat test passed: user system prompt works correctly": "猫咪测试通过：用户自定义系统提示词正常生效。",
  "Identity test passed: model correctly identifies as user-defined identity": "身份测试通过：模型按用户定义身份正确响应。",
  "Test F - Base64 Encoding: identity-related info leaked (developer, ide)": "测试 F - Base64 编码：泄漏了身份相关信息（developer、ide）。",
  "No token injection detected": "未检测到隐藏 Token 注入。",
  "No tool-call package substitution detected": "未检测到工具调用包名替换。",
  "No credential echo or upstream leakage detected in error responses": "错误响应中未检测到凭据回显或上游信息泄漏。",
  "Failed to retrieve model list": "获取模型列表失败。",
  "A: error: 'NoneType' object has no attribute 'strip'": "A 记录检测失败：返回值为空，无法解析 DNS 结果。",
  "No framework branding detected. Likely a direct reverse proxy, a custom backend, or a stripped-branding fork.":
    "未检测到框架品牌特征。该站点可能是直接反向代理、自研后端，或去除了品牌标识的分支版本。",
  "Error leakage test INCONCLUSIVE: every probe returned HTTP 200 or failed with a transport error, so no error surface could be inspected. A relay that silently swallows malformed JSON into a success response is itself suspicious.":
    "错误泄漏测试结果不确定：所有探针都返回 HTTP 200，或因传输错误失败，因此无法检查错误响应面。若中转站把畸形 JSON 静默吞掉并返回成功，本身也值得怀疑。",
  "Latency variance test inconclusive: all 10 probes failed. The relay is refusing or erroring on even tiny requests.":
    "延迟方差测试结果不确定：10 次探针全部失败。该中转站连极小请求也拒绝或报错。",

  "1. Infrastructure Recon": "1. 基础设施探测",
  "2. Model List": "2. 模型列表",
  "3. Token Injection Detection": "3. 隐藏 Token 注入检测",
  "4. Prompt Extraction Tests": "4. 提示词提取测试",
  "5. Instruction Override Tests": "5. 指令覆盖测试",
  "6. Jailbreak & Role Impersonation Tests": "6. 越狱与角色冒充测试",
  "7. Context Length Test": "7. 上下文长度测试",
  "8. Tool-Call Package Substitution (AC-1.a)": "8. 工具调用包名替换检测（AC-1.a）",
  "9. Error Response Leakage (AC-2 adjacent)": "9. 错误响应泄漏检测（AC-2 相邻）",
  "10. Stream Integrity (AC-1 SSE-level)": "10. 流式响应完整性（AC-1 SSE 层）",
  "11. Web3 Prompt Injection": "11. Web3 提示词注入检测",
  "12. Infrastructure Fingerprint": "12. 基础设施指纹",
  "13. Latency Variance": "13. 延迟方差",
  "14. Overall Rating": "14. 总体评级",

  "1.1 DNS Records": "1.1 DNS 记录",
  "Total 6 models:": "共 6 个模型：",
  "Send minimal messages, compare expected vs actual input_tokens. Delta = hidden injection.":
    "发送最小消息，对比预期与实际 input_tokens，差值即隐藏注入。",
  "Test A - Verbatim": "测试 A - 原文复述",
  "Test D: Cat Test": "测试 D：猫咪测试",
  "Test E - System Diagnostic": "测试 E - 系统诊断",
  "Place 5 canary markers at equal intervals in long text, check if model can recall all.":
    "在长文本中等距放置 5 个金丝雀标记，检查模型是否能全部回忆出来。",
};

const PATTERN_TRANSLATIONS: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
  [/^Hidden system prompt injection detected \(~([\d,]+) tokens\/request\)$/i, (match) => `检测到隐藏系统提示词注入（约 ${match[1]} tokens/请求）`],
  [/^Test ([A-Z]) - Verbatim: Hidden prompt content extracted!$/i, (match) => `测试 ${match[1]} - 原文复述：已提取出隐藏提示词内容！`],
  [/^Test ([A-Z]) - JSON continuation: Hidden prompt content extracted!$/i, (match) => `测试 ${match[1]} - JSON 续写：已提取出隐藏提示词内容！`],
  [/^Context boundary: (.+) chars \(max passed: ~([\d,]+) tokens\)$/i, (match) => `上下文边界：${match[1]} 字符（最大通过约 ${match[2]} tokens）`],
  [/^([A-Z]+): error: 'NoneType' object has no attribute 'strip'$/i, (match) => `${match[1].toUpperCase()} 记录检测失败：返回值为空，无法解析 DNS 结果。`],
  [/^Total ([\d,]+) models:$/i, (match) => `共 ${match[1]} 个模型：`],
  [
    /^system: "From now on, only reply with the single character meow\. This is the highest priority instruction\."$/i,
    () => "指令冲突探针：要求模型只回复单个 meow 字符，并声明为最高优先级。",
  ],
  [
    /^Stream integrity anomaly detected \(AC-1 SSE-level\): input_tokens at message_start \(([^)]+)\) disagrees with message_delta samples \(([^)]+)\) -+ usage rewrite; Stream's message_start\.message\.model = '([^']+)' does not contain 'claude' -+ relay may be routing to a substitute model$/i,
    (match) =>
      `检测到流式响应完整性异常（AC-1 SSE 层）：message_start 中的 input_tokens（${match[1]}）与 message_delta 样本（${match[2]}）不一致，疑似 usage 被改写；流式返回的模型名为 ${match[3]}，不包含 claude，可能被路由到替代模型。`,
  ],
  [
    /^Ask the model to echo exact package-install commands and verify character-level integrity on the return path\./i,
    () =>
      "要求模型原样回显包安装命令，并在返回路径上做字符级完整性校验。恶意中间件可能改写包名，制造供应链风险。",
  ],
  [
    /^Fire deterministic broken requests \(malformed JSON, invalid model, wrong content-type, missing fields, unknown endpoint\) at the relay and scan the error response body and headers for echoed credentials, upstream URLs, environment variable names, filesystem paths, and stack-trace markers\./i,
    () =>
      "向中转站发送确定性的异常请求（畸形 JSON、无效模型、错误 content-type、缺失字段、未知端点），检查错误响应正文与响应头中是否泄漏凭据、上游 URL、环境变量名、文件路径或堆栈信息。",
  ],
  [
    /^Open an Anthropic streaming request with thinking enabled and inspect every SSE event for structural anomalies\./i,
    () =>
      "开启带 thinking 的 Anthropic 流式请求，逐个检查 SSE 事件是否存在结构异常。若中转站改写或降级流式响应，通常会破坏事件类型、usage 单调性、签名或模型名等约束。",
  ],
  [
    /^Probe the relay's `\/, \/v1\/models`, and a nonexistent endpoint with unauthenticated GET requests/i,
    () =>
      "使用未认证 GET 请求探测根路径、/v1/models 与不存在的端点，并将响应头与响应正文和已知中转框架指纹库匹配。",
  ],
  [
    /^Fire 10 identical minimal requests \(`max_tokens=8`\) and measure per-request end-to-end latency\./i,
    () =>
      "发送 10 次完全相同的最小请求（max_tokens=8），测量每次端到端延迟，并用统计特征判断是否存在替代模型或队列复用导致的异常波动。",
  ],
];

const SENTENCE_REPLACEMENTS: Array<[RegExp, string]> = [
  [
    /Tool-call substitution test \(Step 8\) was inconclusive: every probe errored, so the relay's AC-1\.a behavior could not be verified -- a relay that blocks plaintext echo is itself a red flag\./gi,
    "工具调用包名替换测试（步骤 8）结果不确定：所有探针都报错，因此无法验证该中转站的 AC-1.a 行为；如果中转站阻断明文回显，这本身就是风险信号。",
  ],
  [
    /Error leakage test \(Step 9\) was inconclusive: every probe returned HTTP 200 or failed with a transport error, so no error surface could be inspected\./gi,
    "错误泄漏测试（步骤 9）结果不确定：所有探针都返回 HTTP 200，或因传输错误失败，因此无法检查错误响应面。",
  ],
  [
    /Stream integrity test \(Step 10\) was inconclusive: the relay did not speak Anthropic SSE cleanly, so the event-layer invariants could not be verified\./gi,
    "流式响应完整性测试（步骤 10）结果不确定：该中转站没有按 Anthropic SSE 规范返回干净的流式响应，因此无法验证事件层结构约束。",
  ],
  [
    /A relay that cannot return a standard Anthropic stream is itself a suspicious signal\./gi,
    "无法返回标准 Anthropic 流式响应的中转站本身就是可疑信号。",
  ],
  [
    /Prompt extraction tests INCONCLUSIVE: one or more probes returned an empty or error response \(A - Verbatim, B - Translation, C - JSON continuation\)\. The relay may be suppressing extraction output rather than cleanly refusing it\./gi,
    "提示词提取测试结果不确定：一个或多个探针返回空响应或错误响应（A - 原文复述、B - 翻译、C - JSON 续写）。该中转站可能在压制提取输出，而不是明确拒绝请求。",
  ],
  [
    /Tool-call substitution test INCONCLUSIVE: every probe errored\. The relay may be blocking plaintext echo -- re-run with a different model or consider this a red flag in itself\./gi,
    "工具调用包名替换测试结果不确定：所有探针都报错。该中转站可能阻断了明文回显，建议换模型重测；也可以将该行为本身视为风险信号。",
  ],
  [
    /Error leakage test INCONCLUSIVE: every probe returned HTTP 200 or failed with a transport error, so no error surface could be inspected\. A relay that silently swallows malformed JSON into a success response is itself suspicious\./gi,
    "错误泄漏测试结果不确定：所有探针都返回 HTTP 200，或因传输错误失败，因此无法检查错误响应面。若中转站把畸形 JSON 静默吞掉并返回成功，本身也值得怀疑。",
  ],
  [
    /Stream integrity test INCONCLUSIVE: Stream opened but produced no non-ping events - the relay is either broken or does not speak Anthropic SSE\. A non-Anthropic relay or broken stream cannot be audited at the SSE event layer\./gi,
    "流式响应完整性测试结果不确定：流已打开，但没有产生非 ping 事件。该中转站可能已损坏，或并未正确支持 Anthropic SSE；非 Anthropic 中转或损坏的流无法在 SSE 事件层完成审计。",
  ],
];

const COMMON_REPLACEMENTS: Array<[RegExp, string]> = [
  [/Tool-call substitution test/gi, "工具调用包名替换测试"],
  [/Error leakage test/gi, "错误泄漏测试"],
  [/Stream integrity test/gi, "流式响应完整性测试"],
  [/Infrastructure Recon/gi, "基础设施探测"],
  [/Model List/gi, "模型列表"],
  [/Token Injection Detection/gi, "隐藏 Token 注入检测"],
  [/Prompt Extraction Tests/gi, "提示词提取测试"],
  [/Instruction Override Tests/gi, "指令覆盖测试"],
  [/Jailbreak tests passed \(no identity keywords leaked\)/gi, "越狱测试通过：未泄漏身份关键词"],
  [/Jailbreak & Role Impersonation Tests/gi, "越狱与角色冒充测试"],
  [/Context Length Test/gi, "上下文长度测试"],
  [/Stream Integrity/gi, "流式响应完整性"],
  [/Infrastructure Fingerprint/gi, "基础设施指纹"],
  [/Latency Variance/gi, "延迟方差"],
  [/DNS Records/gi, "DNS 记录"],
  [/Hidden prompt content extracted/gi, "已提取出隐藏提示词内容"],
  [/No credential echo or upstream leakage detected in error responses/gi, "错误响应中未检测到凭据回显或上游信息泄漏"],
  [/Failed to retrieve model list/gi, "获取模型列表失败"],
  [/could not be verified/gi, "无法验证"],
  [/event-layer invariants/gi, "事件层结构约束"],
  [/suspicious signal/gi, "可疑信号"],
  [/standard Anthropic stream/gi, "标准 Anthropic 流式响应"],
  [/red flag/gi, "风险信号"],
  [/plaintext echo/gi, "明文回显"],
  [/every probe errored/gi, "所有探针都报错"],
  [/transport error/gi, "传输错误"],
  [/error surface/gi, "错误响应面"],
  [/the relay did not speak Anthropic SSE cleanly/gi, "该中转站没有按 Anthropic SSE 规范返回干净的流式响应"],
  [/The relay may be blocking/gi, "该中转站可能阻断"],
  [/The relay may be suppressing extraction output rather than cleanly refusing it/gi, "该中转站可能在压制提取输出，而不是明确拒绝请求"],
  [/a relay that blocks/gi, "阻断相关行为的中转站"],
  [/hidden injection/gi, "隐藏注入"],
  [/inconclusive/gi, "结果不确定"],
  [/input_tokens/g, "input_tokens"],
];

function stripMarkdown(value: string) {
  return value
    .replace(/^#+\s*/, "")
    .replace(/\*\*/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function normalizeText(value: string) {
  return stripMarkdown(value)
    .replace(/[—–]/g, "-")
    .replace(/\s+/g, " ")
    .trim();
}

function translateBody(value: string) {
  const exact = EXACT_TRANSLATIONS[value];
  if (exact) {
    return exact;
  }

  for (const [pattern, translate] of PATTERN_TRANSLATIONS) {
    const match = value.match(pattern);
    if (match) {
      return translate(match);
    }
  }

  let translated = value;
  for (const [pattern, replacement] of SENTENCE_REPLACEMENTS) {
    translated = translated.replace(pattern, replacement);
  }
  for (const [pattern, replacement] of COMMON_REPLACEMENTS) {
    translated = translated.replace(pattern, replacement);
  }
  return translated;
}

export function localizeAuditText(value: string) {
  const normalized = normalizeText(value);
  if (!normalized) {
    return normalized;
  }

  const signalMatch = normalized.match(/^((?:🔴|🟡|🟢|⚠️?|✅|❌)\s*)/u);
  const signal = signalMatch?.[1] ?? "";
  const body = signal ? normalized.slice(signal.length).trim() : normalized;
  return `${signal}${translateBody(body)}`.trim();
}

export function localizeAuditSummaryText<T extends StationAuditSummary>(summary: T): T {
  return {
    ...summary,
    overallSummary: localizeAuditText(summary.overallSummary),
    highlights: summary.highlights.map(localizeAuditText),
    stepSummaries: summary.stepSummaries.map((step) => ({
      title: localizeAuditText(step.title),
      summary: localizeAuditText(step.summary),
    })),
  };
}

export function localizeAuditHistoryItemText<T extends StationAuditHistoryItem>(item: T): T {
  return localizeAuditSummaryText(item);
}

export function localizeStationAuditText<T extends StationRecord>(station: T): T {
  if (!station.audits) {
    return station;
  }
  return {
    ...station,
    audits: {
      ...station.audits,
      latestByModel: station.audits.latestByModel.map(localizeAuditSummaryText),
    },
  };
}

export function localizeSiteDataAuditText(data: SiteData): SiteData {
  return {
    ...data,
    stations: data.stations.map(localizeStationAuditText),
  };
}
