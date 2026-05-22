const AUDIT_SCOPE_ITEMS = [
  "接口可达性：检查 API Base URL 是否可访问，返回是否符合 OpenAI / Anthropic 兼容接口预期。",
  "认证与密钥处理：使用本次输入的临时 API Key 发起检测，不写入配置、localStorage、报告正文或页面 URL。",
  "模型调用表现：记录模型响应、错误类型、风险摘要和可复核的原始 Markdown 报告入口。",
  "站点匹配归档：已收录站点按域名自动匹配，未收录站点按域名生成审计记录，便于后续追踪。",
];

export const AUDIT_FAQ_ITEMS = [
  {
    question: "安全审计会保存我的 API Key 吗？",
    answer: "不会。页面只把 API Key 用于本次本地检测请求，检测完成后会清空输入框，不写入配置文件、浏览器存储、报告正文或页面 URL。",
  },
  {
    question: "审计结果会影响综合排名吗？",
    answer: "不会。综合排名仍基于请求质量、响应时间和采用倍率计算；安全审计只作为站点详情页中的独立风险参考。",
  },
  {
    question: "高风险、中风险和低风险分别表示什么？",
    answer: "风险等级来自黑盒检测摘要。高风险表示存在明显安全或兼容性隐患，中风险表示需要谨慎复核，低风险表示本次检测未发现突出问题。",
  },
  {
    question: "没有收录的中转站可以审计吗？",
    answer: "可以。系统会按输入的 API 域名建立审计记录；如果之后该站点进入收录列表，历史记录仍可用于对照。",
  },
  {
    question: "原始审计报告为什么不参与搜索收录？",
    answer: "原始报告是供复核的 Markdown 文件，可能包含大量技术细节。页面会展示摘要和入口，报告接口本身会设置 noindex，避免搜索结果直接暴露原始报告。",
  },
];

export function AuditSeoContent() {
  return (
    <section className="section audit-seo-section">
      <div className="section-head">
        <div>
          <h2 className="section-title">覆盖范围</h2>
          <p className="section-desc">黑盒审计用于快速判断 AI 中转站接口的可用性、兼容性和基础风险，不替代完整渗透测试或长期稳定性观察。</p>
        </div>
      </div>
      <div className="section-body">
        <div className="grid-2">
          {AUDIT_SCOPE_ITEMS.map((item) => (
            <div className="detail-card" key={item}>
              <h3>{item.split("：", 1)[0]}</h3>
              <p>{item}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function AuditFaqContent() {
  return (
    <section className="section audit-faq-section">
      <div className="section-head">
        <div>
          <h2 className="section-title">常见问题</h2>
          <p className="section-desc">围绕 API Key 处理、风险等级、收录关系和原始报告索引控制的说明。</p>
        </div>
      </div>
      <div className="section-body">
        <div className="grid-2">
          {AUDIT_FAQ_ITEMS.map((item) => (
            <div className="detail-card" key={item.question}>
              <h3>{item.question}</h3>
              <p>{item.answer}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
