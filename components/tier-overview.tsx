import { BadgeDollarSign, CalendarClock, Layers3 } from "lucide-react";

import { formatCurrency, formatMultiplier } from "@/lib/format";
import type { GroupMultiplierRow, RechargeTierRow } from "@/lib/types";

function formatPaymentAmount(tier: RechargeTierRow): string {
  const currency = tier.paymentCurrency?.trim().toUpperCase();
  const amount = tier.paymentAmount ?? tier.rmbAmount;
  if (currency && currency !== "RMB" && currency !== "CNY") {
    if (amount === null || amount === undefined || Number.isNaN(amount)) {
      return "-";
    }
    return `${amount.toFixed(2)} ${currency}`;
  }
  return formatCurrency(amount, "￥");
}

function groupUsageText(group: GroupMultiplierRow): string {
  if (group.usageLabel) {
    return group.usageLabel;
  }
  if (group.codexEligible === true) {
    return "Codex";
  }
  if (group.codexEligible === false) {
    return "非 Codex";
  }
  return "-";
}

export function TierOverview({ groups, rechargeTiers }: { groups: GroupMultiplierRow[]; rechargeTiers: RechargeTierRow[] }) {
  const permanentRechargeTiers = rechargeTiers.filter((tier) => tier.billingType === "permanent");
  const recurringRechargeTiers = rechargeTiers.filter((tier) => tier.billingType !== "permanent");
  const showRechargeDivider = permanentRechargeTiers.length > 0 && recurringRechargeTiers.length > 0;

  return (
    <div className="grid-2 tier-overview-grid">
      <div className="section nested-section">
        <div className="section-head">
          <div>
            <h3 className="section-title section-title-small">
              <Layers3 size={16} />
              <span>分组倍率</span>
            </h3>
            <p className="section-desc">这里只列出该站点当前可见的全部分组与倍率，不展开组合矩阵。</p>
          </div>
        </div>
        <div className="section-body">
          <div className="desktop-table">
            <div className="table-wrap">
              <table className="subtable group-multiplier-table">
                <thead>
                  <tr>
                    <th>分组</th>
                    <th>倍率</th>
                    <th>用途</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.length ? (
                    groups.map((group) => (
                      <tr key={`${group.groupName}-${group.groupMultiplier}`}>
                        <td>{group.groupName}</td>
                        <td className="mono">{formatMultiplier(group.groupMultiplier)}</td>
                        <td>{groupUsageText(group)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={3} className="subtle">
                        暂无分组倍率数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="mobile-card-list">
            {groups.length ? (
              groups.map((group) => (
                <article className="mobile-card mobile-card-compact" key={`${group.groupName}-${group.groupMultiplier}`}>
                  <div className="mobile-card-header">
                    <div className="mobile-card-title-block">
                      <div className="mobile-card-title">{group.groupName}</div>
                    </div>
                  </div>
                  <div className="mobile-metrics-grid mobile-metrics-grid-single">
                    <div className="mobile-metric">
                      <div className="mobile-metric-label">倍率</div>
                      <div className="mobile-metric-value mono">{formatMultiplier(group.groupMultiplier)}</div>
                    </div>
                    <div className="mobile-metric">
                      <div className="mobile-metric-label">用途</div>
                      <div className="mobile-metric-value">{groupUsageText(group)}</div>
                    </div>
                  </div>
                </article>
              ))
            ) : (
              <article className="mobile-card mobile-card-compact">
                <div className="mobile-card-empty subtle">暂无分组倍率数据</div>
              </article>
            )}
          </div>
        </div>
      </div>

      <div className="section nested-section">
        <div className="section-head">
          <div>
            <h3 className="section-title section-title-small">
              <BadgeDollarSign size={16} />
              <span>充值档位</span>
            </h3>
            <p className="section-desc">这里只列出该站点全部充值档位，便于核对月卡、周卡、日卡和按量额度。</p>
          </div>
        </div>
        <div className="section-body">
          <div className="desktop-table">
            <div className="table-wrap">
              <table className="subtable recharge-table">
                <thead>
                  <tr>
                    <th>档位</th>
                    <th>类型</th>
                    <th>实付金额</th>
                    <th>美元额度</th>
                    <th>有效期 / 说明</th>
                    <th>充值位置</th>
                  </tr>
                </thead>
                <tbody>
                  {rechargeTiers.length ? (
                    <>
                      {permanentRechargeTiers.map((tier) => (
                        <tr key={`permanent-${tier.rechargeName}-${tier.billingType}-${tier.rmbAmount}-${tier.usdAmount}`}>
                          <td>{tier.rechargeName}</td>
                          <td>{tier.billingTypeLabel}</td>
                          <td className="mono">{formatPaymentAmount(tier)}</td>
                          <td className="mono">{formatCurrency(tier.usdAmount, "$")}</td>
                          <td>{tier.expiresRule || "-"}</td>
                          <td>{tier.rechargeLocation || "-"}</td>
                        </tr>
                      ))}
                      {showRechargeDivider ? (
                        <tr aria-hidden="true">
                          <td colSpan={6} style={{ padding: 0, borderBottom: 0 }}>
                            <div style={{ height: 1, width: "100%", backgroundColor: "rgba(74, 88, 97, 0.52)" }} />
                          </td>
                        </tr>
                      ) : null}
                      {recurringRechargeTiers.map((tier) => (
                        <tr key={`recurring-${tier.rechargeName}-${tier.billingType}-${tier.rmbAmount}-${tier.usdAmount}`}>
                          <td>{tier.rechargeName}</td>
                          <td>{tier.billingTypeLabel}</td>
                          <td className="mono">{formatPaymentAmount(tier)}</td>
                          <td className="mono">{formatCurrency(tier.usdAmount, "$")}</td>
                          <td>{tier.expiresRule || "-"}</td>
                          <td>{tier.rechargeLocation || "-"}</td>
                        </tr>
                      ))}
                    </>
                  ) : (
                    <tr>
                      <td colSpan={6} className="subtle">
                        暂无充值档位数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="mobile-card-list">
            {rechargeTiers.length ? (
              <>
                {permanentRechargeTiers.map((tier) => (
                  <article className="mobile-card mobile-card-compact" key={`permanent-${tier.rechargeName}-${tier.billingType}-${tier.rmbAmount}-${tier.usdAmount}`}>
                    <div className="mobile-card-header">
                      <div className="mobile-card-title-block">
                        <div className="mobile-card-title">{tier.rechargeName}</div>
                        <div className="mobile-card-subtitle">{tier.billingTypeLabel}</div>
                      </div>
                    </div>
                    <div className="mobile-metrics-grid">
                      <div className="mobile-metric">
                        <div className="mobile-metric-label">实付金额</div>
                        <div className="mobile-metric-value mono">{formatPaymentAmount(tier)}</div>
                      </div>
                      <div className="mobile-metric">
                        <div className="mobile-metric-label">美元额度</div>
                        <div className="mobile-metric-value mono">{formatCurrency(tier.usdAmount, "$")}</div>
                      </div>
                    </div>
                    <div className="mobile-card-detail-grid">
                      <div className="mobile-detail-row">
                        <div className="mobile-detail-label">有效期说明</div>
                        <div className="mobile-detail-value">{tier.expiresRule || "-"}</div>
                      </div>
                      <div className="mobile-detail-row">
                        <div className="mobile-detail-label">充值位置</div>
                        <div className="mobile-detail-value">{tier.rechargeLocation || "-"}</div>
                      </div>
                    </div>
                  </article>
                ))}
                {showRechargeDivider ? (
                  <div aria-hidden="true" style={{ height: 1, margin: "12px 0", backgroundColor: "rgba(74, 88, 97, 0.52)" }} />
                ) : null}
                {recurringRechargeTiers.map((tier) => (
                  <article className="mobile-card mobile-card-compact" key={`recurring-${tier.rechargeName}-${tier.billingType}-${tier.rmbAmount}-${tier.usdAmount}`}>
                    <div className="mobile-card-header">
                      <div className="mobile-card-title-block">
                        <div className="mobile-card-title">{tier.rechargeName}</div>
                        <div className="mobile-card-subtitle">{tier.billingTypeLabel}</div>
                      </div>
                    </div>
                    <div className="mobile-metrics-grid">
                      <div className="mobile-metric">
                        <div className="mobile-metric-label">实付金额</div>
                        <div className="mobile-metric-value mono">{formatPaymentAmount(tier)}</div>
                      </div>
                      <div className="mobile-metric">
                        <div className="mobile-metric-label">美元额度</div>
                        <div className="mobile-metric-value mono">{formatCurrency(tier.usdAmount, "$")}</div>
                      </div>
                    </div>
                    <div className="mobile-card-detail-grid">
                      <div className="mobile-detail-row">
                        <div className="mobile-detail-label">有效期说明</div>
                        <div className="mobile-detail-value">{tier.expiresRule || "-"}</div>
                      </div>
                      <div className="mobile-detail-row">
                        <div className="mobile-detail-label">充值位置</div>
                        <div className="mobile-detail-value">{tier.rechargeLocation || "-"}</div>
                      </div>
                    </div>
                  </article>
                ))}
              </>
            ) : (
              <article className="mobile-card mobile-card-compact">
                <div className="mobile-card-empty subtle">暂无充值档位数据</div>
              </article>
            )}
          </div>
          <div className="footer-note inline-actions">
            <CalendarClock size={14} />
            这里按“分组倍率表”和“充值档位表”拆开展示，不做分组 × 充值档位的排列组合。
          </div>
        </div>
      </div>
    </div>
  );
}
