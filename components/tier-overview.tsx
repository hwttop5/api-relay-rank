import { BadgeDollarSign, CalendarClock, Layers3 } from "lucide-react";

import { formatCurrency, formatMultiplier } from "@/lib/format";
import type { GroupMultiplierRow, RechargeTierRow } from "@/lib/types";

export function TierOverview({ groups, rechargeTiers }: { groups: GroupMultiplierRow[]; rechargeTiers: RechargeTierRow[] }) {
  return (
    <div className="grid-2">
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
              <table className="subtable">
                <thead>
                  <tr>
                    <th>分组</th>
                    <th>倍率</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.length ? (
                    groups.map((group) => (
                      <tr key={`${group.groupName}-${group.groupMultiplier}`}>
                        <td>{group.groupName}</td>
                        <td className="mono">{formatMultiplier(group.groupMultiplier)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={2} className="subtle">
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
                    <th>人民币</th>
                    <th>美元额度</th>
                    <th>有效期 / 说明</th>
                    <th>充值位置</th>
                  </tr>
                </thead>
                <tbody>
                  {rechargeTiers.length ? (
                    rechargeTiers.map((tier) => (
                      <tr key={`${tier.rechargeName}-${tier.billingType}-${tier.rmbAmount}-${tier.usdAmount}`}>
                        <td>{tier.rechargeName}</td>
                        <td>{tier.billingTypeLabel}</td>
                        <td className="mono">{formatCurrency(tier.rmbAmount, "￥")}</td>
                        <td className="mono">{formatCurrency(tier.usdAmount, "$")}</td>
                        <td>{tier.expiresRule || "-"}</td>
                        <td>{tier.rechargeLocation || "-"}</td>
                      </tr>
                    ))
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
              rechargeTiers.map((tier) => (
                <article className="mobile-card mobile-card-compact" key={`${tier.rechargeName}-${tier.billingType}-${tier.rmbAmount}-${tier.usdAmount}`}>
                  <div className="mobile-card-header">
                    <div className="mobile-card-title-block">
                      <div className="mobile-card-title">{tier.rechargeName}</div>
                      <div className="mobile-card-subtitle">{tier.billingTypeLabel}</div>
                    </div>
                  </div>
                  <div className="mobile-metrics-grid">
                    <div className="mobile-metric">
                      <div className="mobile-metric-label">人民币</div>
                      <div className="mobile-metric-value mono">{formatCurrency(tier.rmbAmount, "￥")}</div>
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
              ))
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
