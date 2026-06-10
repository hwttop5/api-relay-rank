import type { StatementPageData } from "@/lib/types";

const HIGHLIGHT_PHRASE = "所以本排名更关注各中转站的服务下限。";
const DISCLAIMER_EMPHASIS = "部分中转站外链使用邀请链接，可能为测试账号带来少量额度奖励。这些额度将用于维持长期测试、扩大数据样本并持续更新排名；排名数据、评分和排序不受邀请链接影响，仅供参考。";

function normalizeDeclarationText(text: string) {
  return text.replace(`（${HIGHLIGHT_PHRASE}）`, HIGHLIGHT_PHRASE);
}

function renderEmphasizedText(text: string) {
  if (text.includes(HIGHLIGHT_PHRASE)) {
    const [before, after] = text.split(HIGHLIGHT_PHRASE, 2);
    return (
      <>
        {before}
        所以
        <strong>本排名更关注各中转站的服务下限。</strong>
        {after}
      </>
    );
  }

  if (text.includes(DISCLAIMER_EMPHASIS)) {
    const [before, after] = text.split(DISCLAIMER_EMPHASIS, 2);
    return (
      <>
        {before}
        <strong>{DISCLAIMER_EMPHASIS}</strong>
        {after}
      </>
    );
  }

  return text;
}

function splitStatementLine(item: string) {
  for (const separator of ["：", "=", ":"]) {
    if (item.includes(separator)) {
      const [label, value] = item.split(separator, 2);
      return { label: label.trim(), value: value.trim() };
    }
  }

  return { label: "", value: item.trim() };
}

function StatementList({ items }: { items: string[] }) {
  return (
    <div className="statement-list">
      {items.map((item) => {
        const { label, value } = splitStatementLine(item);
        return (
          <div className="statement-row" key={item}>
            {label ? <p className="statement-label">{label}</p> : null}
            <p className="statement-value">{label ? renderEmphasizedText(value) : renderEmphasizedText(item)}</p>
          </div>
        );
      })}
    </div>
  );
}

function BulletTextList({ items }: { items: string[] }) {
  return (
    <div className="bullet-list">
      {items.map((item) => (
        <div className="bullet-item" key={item}>
          <span className="bullet-prefix">-</span>
          <p className="bullet-copy">{renderEmphasizedText(item)}</p>
        </div>
      ))}
    </div>
  );
}

export function DeclarationPanels({ data }: { data: StatementPageData }) {
  const coreItems =
    data.declaration.coreItems && data.declaration.coreItems.length
      ? data.declaration.coreItems
      : [data.declaration.scoring, data.declaration.formula, data.declaration.adoptedMultiplierRule].filter(Boolean);
  const conclusionItems = data.declaration.conclusion ?? [];
  const environmentParagraphs = data.declaration.environment
    .split(/\n{2,}/)
    .map((item) => normalizeDeclarationText(item.trim()))
    .filter(Boolean);

  return (
    <div className="declaration-layout">
      {conclusionItems.length ? (
        <div className="notice-panel notice-panel-primary declaration-hero">
          <p className="notice-title">最终结论</p>
          <BulletTextList items={conclusionItems} />
        </div>
      ) : null}

      <div className="declaration-columns">
        <div className="declaration-side">
          <div className="notice-panel declaration-copy-panel declaration-copy-full">
            <p className="notice-title">环境与口径</p>
            <BulletTextList items={environmentParagraphs} />
          </div>
        </div>

        <div className="declaration-side declaration-side-split">
          <div className="notice-panel declaration-compact-panel">
            <p className="notice-title">核心公式</p>
            <StatementList items={coreItems} />
          </div>
          <div className="notice-panel declaration-compact-panel">
            <p className="notice-title">补充说明</p>
            <StatementList items={data.declaration.items} />
          </div>
        </div>
      </div>
    </div>
  );
}
