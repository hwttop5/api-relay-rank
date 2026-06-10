# 前端展示规则

## /ranking 正式榜展示规则

- `/ranking` 展示层问题优先只改 `components/ranking-dashboard.tsx` 和 `app/globals.css`，不要为了修 UI 手工编辑 `data/site-data.json`、CSV 或数据生成脚本。
- 正式综合排名要明示样本层级：同一时段内，请求样本数 `>= 10` 的站点优先排名，`< 10` 的低样本站点仍保留在正式榜但整体置后。
- 前端所有排序模式都必须先保留样本层级，再在同一层级内按用户选择的综合分、正确率、响应时间或采用倍率排序，避免用户切换排序后把 9 条样本的站点排到 10 条样本站点前面。
- rank 值仍来自生成数据，低样本站点置后后 rank 连续；分页只改变展示范围，不重新计算 rank。
- 页面说明只写排名口径，不把站点个案、账号封禁、Cookie 或登录态细节放到 `/ranking`。
- 当前正式 all-hours 榜为 `72` 个站点。展示缺口按分组倍率、充值档位、公告三类判断；已确认空公告不算缺数据，只有 `missing`、`failed`、`blocked`、`login_required`、`public_missing` 等未确认状态才需要展示为缺口。
- 当前正式榜仍缺数据的站点只缺公告：`new.sharedchat.cc`、`freemodel`、`aicodelink`、`api.baobu.xyz`、`icodex.pro`、`www.thinkai.tv`、`crazyrouter.com`。页面不要把这些站点误判成缺分组倍率或缺充值档位。
- 正式综合排名表和未纳入表的最后一列要保持同一套文案、交互和宽度：表头为 `操作`，按钮为 `详情`，按钮样式复用 `.tiny-button`。

## /ranking 未纳入表展示规则

- “未纳入正式排名的收录站点”如果展示样本数，口径应来自 `station.quality[window].requestSamples`；`0` 是有效样本数，只有对应质量行不存在才显示 `-`。
- 未纳入表的样本字段要和实际口径一致，使用 `工作时段样本`、`非工作时段样本`、`全部时段样本`，单元格只展示样本数量。
- 未入榜表必须展示“未入榜原因”。用户看到分组、充值和公告都有时，仍可能因为缺请求样本、费用待人工复核、缺正式费用行或缺分组/充值证据而不能进入排行榜。
- 未入榜原因优先级固定为：缺分组/充值证据 -> 费用待人工复核 -> 缺正式费用行 -> 缺请求样本。已具备正式费用行的站点不要继续套用旧人工复核文案。
- `正式费用行：0` 表示当前没有可用于正式排名的费用证据行，不等于详情页充值档位数量为 0；解释时要指向正式费用证据链。
- 未入榜表“类型”列必须来自 `stationTypeShortLabel`。如果 live probe 已根据结构化充值/套餐档位推断出 `mixed`、`subscription` 或 `non_subscription`，类型列不要继续显示“待补证据”。
- live probe 已抓到结构化分组和有效充值/套餐时，构建脚本会把这些档位计入 `verifiedTierCount`。这类站点如果请求样本为 0，应显示“缺请求样本”，不要继续显示“缺正式费用行”。
- `费用待人工复核` 只用于缺正式费用行且确实需要人工确认的站点；已有正式费用行的站点即使倍率很高，也不能继续显示该文案。
- 未纳入表桌面端列顺序固定为：站点、网址、类型、平台判断、未入榜原因、最低倍率、全部时段样本、核验档位、公告数、操作。“最低倍率”必须在第 6 列。
- 移动端未排名站点卡片要在指标区同步显示“最低倍率”，并复用现有倍率格式化规则；无法计算时显示 `-`。
- “最低倍率”只解释未入榜站点的可见成本线索，不改变正式排名、评分、`effectiveMultiplier`、排序或 `rankedStationCount`。
- 未纳入表需要单独的列宽策略，但不要把它扩散到全局 `.data-table`。优先用 `colgroup` 给未纳入表声明列比例，再让 `col-action` / `table-action-cell` 继续走全局宽度规则。
- 前两列不要为了撑满页面占用过多空间；多余宽度应更均匀分配给类型、平台判断、样本、核验档位和公告数等中后部列。
- 典型验收案例：`Nerverun` 类型显示“混合型”且未入榜原因显示“缺请求样本”；`FishXCode`、`MooseCloud` 显示缺请求样本；`VoAPI` 在正式排名和详情页展示采用倍率，不进入未纳入表。

## /stations 详情页展示规则

- 详情页已有分组、充值、公告不等于一定入榜。前端文案要区分“详情证据完整”和“正式排名条件满足”。
- 分组表如果存在 `usageLabel` / `codexEligible`，必须展示用途；`codexEligible=true` 显示 Codex，`codexEligible=false` 显示 Claude Code。
- sub2api 绿色分组显示为 Codex，橙色 Claude Code 分组不得参与最低倍率；ProdBbroot 的橙色 `default` 不参与最低倍率或采用倍率解释。
- 充值表第一金额列使用“实付金额”，不要固定写“人民币”；当 `paymentCurrency=USDC` 时应显示 USDC，而不是 `￥`。
- `/ranking` 顶部说明和未入榜表要使用同一成本口径：`Codex-like 最小非 0 分组倍率 × 实付金额 ÷ 到账美元额度`；有明确用途标记时，先排除非 Codex 分组。
- Fushengyunsuan 当前分组表和排名快照应显示 `vip=0.05` / `企业生图专线=0.05` 及采用倍率 `0.05`。如果公告区展示历史公告中的 `0.0075x`，只作为历史公告文本保留，不应出现在当前分组表、未入榜最低倍率或排名采用倍率中。
- 详情页与 `/ranking` 的采用倍率、分组、充值档位、未入榜状态和详情页证据数量必须一致。

## /audit 展示与分页规则

- JSON/local 模式下，`/audit` 历史列表继续扫描 `data/_audit_runs/**/summary.json`，并跳过失败 run。
- PostgreSQL 模式下，`/audit` 优先读取 `station_audit_runs`；只有 `SITE_DATA_ALLOW_FILE_FALLBACK=1` 且 DB 读取失败时才回退文件扫描。
- 历史列表的 `reportUrl` 仍使用 `/api/audit-report?station=...&model=...&run=...`，报告正文仍来自 `_audit_runs` 目录中的 `report.md`。
- 审计历史表是服务端分页 UI：默认 `page=1`、`pageSize=10`、按 `executedAt desc`；`station/model/verdict/timeRange/sort/direction/page/pageSize` 都来自 URL query。
- PostgreSQL 模式下，筛选、排序和分页必须在 `station_audit_runs` 查询中完成，使用 `where/order by/limit/offset`。JSON/local 模式允许文件扫描 fallback，但传给客户端的仍只能是当前页。
- 审计完成后可以把新 run 临时合并到当前页顶部，但只能在当前筛选和第一页匹配时插入；随后依赖 `router.refresh()` 重新读取服务端分页结果，不能恢复为全量 history。
- `/audit` 首屏不应把完整历史传给客户端；所有筛选、排序和翻页状态都必须由 URL query 驱动，刷新或分享链接后仍能恢复同一页视图。
- 页面验证时要同时确认历史记录数量、筛选、排序、分页、URL query 和报告链接；不要只看站点详情页里的最新审计摘要。线上性能验收要记录 `/audit` HTML 大小、TTFB 和 total time，和服务端分页前的约 `1.16 MB HTML / 2.5s TTFB / 5.4s total` 做对比。

## 消息通知弹窗

- 右上角“消息通知”按钮常驻，关闭状态不会隐藏入口；点击后应无视“今日已读 / 永久关闭”，直接重新打开弹窗。
- 首次访问只有在本地公告缓存同时存在有效 `title + contentHtml/content` 时才自动弹窗。公告读取入口是 `/api/contact-ad`，但该接口本身只读本地缓存。
- “今日已读”和“永久关闭”只影响自动弹窗，不影响用户后续手动点开消息通知。
- 没有公告正文、缓存缺失或本地读取失败时，不自动弹窗；用户手动打开时展示空态文案“暂无公告”。
- 弹窗标题直接显示 GitHub issue 标题，正文优先渲染清洗后的 issue `body_html`，没有 HTML 缓存时再回退到 issue Markdown，不再依赖或解析正文 frontmatter。
- 弹窗正文与站点详情页公告流共用同一套渲染规则；表格、二维码图片和普通段落都按公告缓存中的安全 HTML / Markdown 输出，不直接暴露原始 HTML。
- 公告图片一律走本地资源地址 `/api/contact-ad/assets/...`，不直接请求 GitHub 图床。二维码类图片要按表格或图片本身居中规则展示，避免移动端溢出或左右错位。
- 弹窗交互保留通用关闭行为：点击遮罩或按 `Esc` 可关闭；空态弹窗不显示“今日已读 / 永久关闭”操作按钮。

## 邀请链接展示边界

- 可点击的站点访问入口优先使用 `config/station_invite_links.json` 生成的邀请链接，包括 `/ranking` 正式榜行、未入榜收录站点外链和 `/stations/[station]` 顶部“打开官网”按钮。
- `station.url` 继续保留官网链接；详情证据、公告来源、审计报告、SEO JSON-LD 和审计运行目标不能改用邀请链接。
- 邀请链接披露文案保留在 `/statement`；`/ranking` 正式综合排名标题区不要重复展示橙色邀请链接说明，避免挤占核心排名信息。
- 新入榜正式榜站点如果暂未配置邀请链接，页面临时显示官网原链，并由刷新校验报告记录为 `fallback_official_url`；补齐邀请链接后只需更新 `config/station_invite_links.json` 并重建站点数据。
- 用户已确认 `new.sharedchat.cc`、`coolplay`、`muyuan.do`、`lumibest`、`icodex.pro`、`api.code-relay.com` 没有邀请链接。它们可以长期显示官网回退链接，`fallback_official_url` 对这些站点不应展示成错误或待补抓异常。

## 验证清单

- 运行 `npx tsc --noEmit`，确认 TSX 与类型没有回归。
- 打开本地 `/ranking`，检查两张表最后一列都是 `操作` / `详情`，按钮宽度和单元格宽度一致。
- 抽查正式榜和未纳入表重点站点：`HelloCode`、`PrintcapAI`、`VoAPI` 应在正式排名中展示采用倍率；`FishXCode`、`MooseCloud` 应显示缺请求样本。
- 打开 `/stations/<station>` 核对对应详情页，确认采用倍率、分组、充值档位和未入榜状态与 `/ranking` 一致。
- 页面核对要同时看 `/ranking` 和 `/stations/<station>` 的展示是否一致；文档不要求规定截图保存路径。
- 用浏览器实际测量列宽，不只看 CSS 预期值；表格布局会按内容、百分比和容器宽度重新分配像素。
- 宽屏下确认未纳入表撑满容器，同时前两列不过宽、三个样本列紧凑、最后一列仍与正式排名表一致。
