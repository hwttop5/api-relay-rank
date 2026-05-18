# 数据刷新复盘

## 本次经验

- 正式排名从约 30 个站点降到 3 个，核心原因不是当前 Codex Manager 日志不足，而是父目录的核验证据不完整：`tabbit-audit-profile/` 缺失、`verified_multiplier_inputs.csv` 为空时，大量 `high_tabbit_logged_in` 和 `manual_verified` 倍率证据无法参与正式排名。
- 恢复旧会话的登录态核验证据和非空人工核验输入后，正式排名恢复到本次参考规模：工作时段 27 个、非工作时段 31 个、全时段 32 个。
- 周末全天必须归入非工作时段。刷新数据后需要同时检查脚本口径、`site-data.json` 的 `timeWindows`、特别声明文案和页面上的时段说明。
- 本地工具、代理网关和临时服务不能进入公开站点列表。本次 `Tabit2api` 来自 `http://127.0.0.1:50124`，只有质量/待证据记录，没有公开站点 URL 和已核验倍率，构建公开数据时应过滤掉这类本地地址或空 URL 站点。

## 外部输入

数据刷新不只依赖仓库内代码，还依赖 `C:\Users\ttop5\Documents\projects` 下的外部输入：

- `audit_proxy_multipliers.py`：日志重算主脚本。
- `tabbit-audit-profile/`：登录态 live probe 证据，当前恢复目标包含 26 个 `*-live-auth-probe.json` 和 `pending-stations-api-probes.json`。
- `verified_multiplier_inputs.csv`：非空人工核验输入；如果只剩表头，正式排名会大幅缩水。
- `capture_tabbit_live_probes.py`：后续重新抓登录态证据时使用。

不要在未确认当前浏览器登录态可用时运行带 `--capture-live-probes` 的刷新，否则可能用空状态覆盖已恢复证据。

## 推荐刷新顺序

```powershell
npm run site:refresh-manual
npm run site:announcements
npm run site:tiers
npm run site:data
```

本地确认前不要执行 `git add`、提交或推送。需要上线时再单独检查差异并提交数据文件。

## 刷新后检查

```powershell
python -m unittest tests/test_build_site_data.py
npm run build
rg -n "Tabit2api|tabit2api|127\.0\.0\.1:50124" data/site-data.json
git status --short --branch
git diff --stat -- data/site-data.json data/_public_fetch
```

重点确认：

- `generatedAt` 已更新。
- `rankedStationCount` 与三个 formal CSV 行数一致。
- `timeWindows` 和特别声明仍明确写着周末全天计入非工作时段。
- `multiplier_tiers.csv` 中有大量 `high_tabbit_logged_in`，并保留 `manual_verified` 样本。
- 公开 `data/site-data.json` 不包含本地地址、私人账号标识或只存在于本地代理项目中的站点。

## 站点收费信息补抓经验

## sub2api 平台判断与登录边界

- `sub2api` 的公开首页通常会显示为 `站点名 - AI API Gateway`，并注入 `window.__APP_CONFIG__`。不能再把所有 `AI API Gateway` 页面默认归为 `new-api-like`。
- 平台判断优先级：明确 `New API` generator/title 仍判为 `new-api`；包含 `sub2api` / `subscription to api` 字样，或同时具备 `AI API Gateway` 标题和 sub2api 公共设置指纹时判为 `sub2api`；其余只含通用 token/console 线索的页面才落到 `new-api-like`。
- sub2api 上游源码中，用户公告 `/api/v1/announcements` 挂在已登录路由下；未登录公开抓取只能采集首页配置、文档链接、菜单项等公共信息，不能视为完整公告。
- sub2api 的分组倍率、订阅和充值计划也通常需要登录：`/api/v1/groups/available`、`/api/v1/groups/rates`、`/api/v1/subscriptions`、`/api/v1/payment/config`、`/api/v1/payment/plans` 均属于认证路由。公开 `/api/v1/settings/public` 只能补充站点配置，不替代登录态核验。

- 旧硬编码收费档位要优先核对是否仍有效。本次 Nexus 已从客服套餐切到站内钱包充值，必须移除旧 `VIP/PRO/MAX monthly` 口径，改用登录态 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info` 证据。
- v1-like 站点的 `recharge_fee_rate` 不能直接忽略。Nexus 返回充值倍率 `34.99` 且手续费 `1.6%`，排名里的人民币成本应按含手续费实付金额计算。
- 公开页和登录态接口要分开看：`/pricing`、`/api/pricing` 可作为公开快照，但 Loomex、Nexus、nbtoken 这类关键信息仍以登录后的分组/充值 API 为准。
- `window.__APP_CONFIG__` 中的 `payment_enabled` / `purchase_subscription_enabled` 只能作为站点类型提示：可把未知站点修正为非包月型、包月型或混合型，但不能生成充值档位、核验档位或采用倍率。PrintCap 这次就是只确认“开启余额充值”，具体金额/到账额度仍需登录或人工核验。
- Turnstile 阻塞时不要伪造证据。PrintCap、OpenTK、OneXModel 这类登录接口如果返回 Turnstile 校验失败，只记录阻塞状态；已有旧 probe 可继续使用，缺失站点需后续浏览器人工通过校验后再抓。
- 未上榜站点的请求样本只来自 Codex Manager 日志，不能用站点后台补。收费档位能补齐，正式排名仍必须同时具备请求质量样本和高置信倍率证据。
- 采用倍率不能再按“全站最低已核验倍率”直接取值。正式排名必须优先使用 Codex 口径分组中的最小非 0 倍率，其中 `default` 也视为 Codex 可用分组；只有缺少明确 Codex/default 分组时，才回退到最低非 Claude 分组。

## 数据缺口与详情页展示

- 刷新前后要盘点每个站点的三类详情页证据：分组倍率、充值档位、公告。分组倍率和充值档位缺口会影响正式成本口径；公告缺口只影响详情页展示，不应伪造成空公告。
- `tabbit-audit-profile/*-live-auth-probe.json` 是补齐 sub2api 详情数据的首选来源。v1/sub2api probe 应尽量包含 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/payment/plans`、`/api/v1/announcements`。
- 公告接口返回空列表、接口未被抓取、接口需要登录、接口抓取失败要分开标注。详情页的“数据证据状态”用于展示这些状态，避免用户把“暂无公告”和“没有抓到公告接口”混为一谈。
- PrintCap 当前公开配置只能确认 `payment_enabled=true` 且 `purchase_subscription_enabled=false`，可用于修正类型为非包月型；分组倍率、充值档位和公告仍以登录态 probe 或人工核验为准。
- 如果登录被 Turnstile/腾讯验证码等风控挡住，但用户提供了可辨认截图，可把截图作为 `verified_multiplier_inputs.csv` 的 `manual_verified` 来源；本次 PrintCap 完整充值图确认唯一分组为 `GPT-MIX 1x`，快捷充值档位为 `10/20/50/100/200/500/1000/2000/5000 RMB`，自定义金额与快捷档位均按 `1 CNY = 2 USD` 到账，因此采用倍率按 Codex 口径计算为 `1 × RMB ÷ (RMB × 2) = 0.5`。公告仍不能由截图推断，继续标为需要登录。
- 公告补抓 helper `scripts/scrape_missing_announcements.py` 只记录登录尝试状态和接口响应，不保存密码或 token；写入 probe 前会脱敏 token 类字段。运行时通过 `API_RELAY_SCRAPE_EMAIL` / `API_RELAY_SCRAPE_PASSWORD` 传入账号密码，不要把凭据写进脚本。

## 近期排查补充（2026-05-18）

- 排查排名异常时，先按 `Codex Manager DB -> quality_metrics.csv -> formal ranking CSV -> data/site-data.json` 四层对账，再看页面。只盯着页面或只看某一个 CSV，很容易把“分类遗漏”误判成“站点消失”。
- 时间窗口径必须先确认再改脚本。之前把请求样本误加了“最近三天”截断，直接把 `nexus` 这类旧日志站点从正式排名里清空了；这类改动必须先用独立 SQL 核对样本时间分布。
- 新站点分类要补全到脚本里的 `classify_station()`，否则会出现“DB 里有请求、费用证据也有，但质量 CSV 里是 0”的假缺失。`opentk` 就是这类遗漏，补分类后才重新进入正式排名。
- 私有账号键、本地代理地址和临时站点不能进入公开站点池。像 `ttop5`、`127.0.0.1:8787`、`tabit2api` 这类条目只能留在内部排查链路，不能写进公开站点列表或前端 JSON。
- 新站点是否收录和是否进入正式排名要分开处理。`clawto` 已按独立站点收录，但授权接口仍只拿到 `login_required`，因此只能留在站点列表，不能伪造倍率、充值档位或公告。
- 只要改了采样、分类或过滤规则，必须马上做三步验证：重新生成父级 CSV、重建 `site-data.json`、再跑 `python -m unittest tests/test_build_site_data` 和 `npm run build`。最后还要强刷本地页面，确认页面读到的是新生成的数据而不是旧缓存。
