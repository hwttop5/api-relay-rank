import { AppShell, StatusChip } from "@/components/app-shell";
import { StationSubmissionForm } from "@/components/station-submission-form";
import { getAuthenticatedGithubUser, isGithubAuthConfigured } from "@/lib/auth";
import { formatCompactCount } from "@/lib/format";
import { getPageViewStats } from "@/lib/page-view-stats";
import { hasDatabaseUrl } from "@/lib/postgres";
import { absoluteUrl, pageMetadata, safeJsonLd } from "@/lib/seo";
import { getSiteData } from "@/lib/site-data";
import { buildShellData } from "@/lib/site-data-view";

const PAGE_TITLE = "申请收录 AI 中转站";
const PAGE_DESCRIPTION = "站长提交 AI 中转站官网、付费类型、倍率截图、测试 BaseURL 和临时 API Key，申请进入 AI 中转站监视者收录审核。";

export const dynamic = "force-dynamic";

export const metadata = pageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  pathname: "/submit",
});

const REVIEW_NOTES = [
  "提交后不会立即进入正式排名；正式排名仍需要人工复核费用证据、模型可用性和真实请求样本。",
  "分组倍率截图需能看清页面来源、分组名称、模型倍率；充值倍率截图需能看清充值金额和到账额度。",
  "请优先提交非包月/余额消费类信息；包月、公益或混合计费站点会单独判断展示方式。",
  "邀请链接暂不在申请表收集；如后续需要配置，会由站主使用自己的账号注册并维护。",
  "如截图或测试信息无法复核，申请可能会被暂缓收录或退回补充。",
];

const TEST_NOTES = [
  "测试 Key 仅用于连通性、模型可用性、倍率核验和小规模响应质量抽样。",
  "请放在最低倍率、Codex 可用分组，并保留测试额度。或者直接提供有一定额度的测试账号。",
  "不要提交主账号 Key、无限额 Key 或包含敏感业务数据的账号。",
  "测试通常会在提交后 3-7 天内陆续产生使用数据，请耐心等待样本采集。",
  "如测试 Key 失效、额度不足或 BaseURL 不可访问，申请会进入待补充状态。",
];

export default async function SubmitPage() {
  const [siteData, viewer, pageViewStats] = await Promise.all([getSiteData(), getAuthenticatedGithubUser(), getPageViewStats()]);
  const shellData = buildShellData(siteData, siteData.stations.length);
  const webPageJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: PAGE_TITLE,
    description: PAGE_DESCRIPTION,
    url: absoluteUrl("/submit"),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(webPageJsonLd) }} />
      <AppShell
        active="submit"
        data={shellData}
        footerMeta={<>累计 PV {formatCompactCount(pageViewStats.totalPv)}</>}
        topbarMetaClassName="topbar-meta-inline-mobile"
        actions={
          <>
            <StatusChip label="GitHub 登录提交" tone="accent" />
          </>
        }
      >
        <section className="section submission-section">
          <div className="section-head">
            <div>
              <h1 className="section-title">{PAGE_TITLE}</h1>
              <p className="section-desc">请一次性提供官网、费用口径、截图和测试凭据，方便人工核验和后续小样本测试。</p>
            </div>
            <StatusChip label="站长入口" tone="blue" />
          </div>
          <div className="section-body">
            <div className="submission-layout">
              <div className="submission-main">
                <StationSubmissionForm
                  viewer={viewer}
                  authConfigured={isGithubAuthConfigured()}
                  databaseConfigured={hasDatabaseUrl()}
                  reviewNotes={REVIEW_NOTES}
                  testNotes={TEST_NOTES}
                />
              </div>
            </div>
          </div>
        </section>
      </AppShell>
    </>
  );
}
