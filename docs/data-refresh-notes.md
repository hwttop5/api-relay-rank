# 数据刷新维护手册

本文档记录 `api-relay-rank` 的数据刷新流程、证据采用规则和排查经验。README 只保留快速上手；数据刷新细节统一维护在这里。

## 核心原则

- 生成数据只能走脚本。不要手工编辑 `data/site-data.json`、`data/_public_fetch/`、质量 CSV 或排名 CSV。
- 失败和空结果不能覆盖旧成功证据。分组倍率、充值档位、公告、公开快照和 live probe 都遵守保旧规则。
- 缺口站点先用脚本补抓真实数据，再用浏览器核对页面；浏览器能看到但脚本抓不到时，优先修抓取入口、解析逻辑、归一化逻辑和文档，避免一次性手补 JSON。
- 正式排名门槛不放松：必须同时具备 Codex Manager 请求样本和可正式采用的费用证据。
- 凭据不入库。账号、密码、token、Cookie、浏览器会话和本地代理信息不能写入代码、文档、JSON 输出或日志。
- 本地工具、回环地址、私有账号键和临时代理服务不能进入公开站点池，只能留在内部排查链路。
- 周末全天归入非工作时段。刷新后要核对脚本口径、`site-data.json` 的 `timeWindows`、声明文案和页面展示。

## 数据来源与权威顺序

- Codex Manager `request_logs` 是质量样本来源，只统计 `/v1/responses`。站点后台数据不能补请求样本。
- `data/codex-log-refresh-state.json` 是日志累计指标的主存储，保存 cursor、三个时段累计指标、耗时样本、首包耗时样本和近期去重 key。旧日志清理后，历史排名只能从这个 state 延续。
- 公开快照位于 `data/_public_fetch/`，用于公开公告、公开价格、公开配置和可复核店铺信息。公开配置只能提示站点类型，不能凭自然语言或猜测生成正式费用行。
- 登录态证据位于 `../tabbit-audit-profile/`，是 sub2api/v1 分组、支付、公告详情的首选来源。结构化分组和充值/套餐同时抓到时，可计入已核验费用证据；仓库外目录可以作为相对路径引用，不要扩展成本机绝对路径。
- `verified_multiplier_inputs.csv` 用于人工核验输入。截图、官方店铺或浏览器人工核验可以进入这里，但必须可复核，且不能包含凭据。
- `data/site-data.json` 是前端主数据源，也是失败/空抓取时保留旧详情数据的基线之一；它不是人工编辑入口。

## 刷新流程

本地普通刷新：

```powershell
npm run site:refresh-manual
```

`site:refresh-manual` 当前执行顺序：

1. 运行 `audit_proxy_multipliers.py`，做增量日志分析、新站点发现和排名 CSV 生成。
2. 运行 `scripts/build_site_data.py`，重建 `data/site-data.json`。
3. 运行 `scripts/fetch_public_content.py --announcements --multiplier-snapshots --skip-build --quiet`，刷新公开快照。
4. 如果存在 `API_RELAY_SCRAPE_EMAIL` 和 `API_RELAY_SCRAPE_PASSWORD`，运行 `scripts/scrape_missing_announcements.py --all-stations --write-probes`；缺凭据时跳过登录态补抓。
5. 再次运行审计脚本和 `scripts/build_site_data.py`，把新快照和 probe 纳入最终输出。

可选命令：

```powershell
python scripts/refresh_quality_rankings.py --capture-live-probes
python scripts/refresh_quality_rankings.py --full-log-rebuild
```

- `--capture-live-probes` 会先调用 `capture_tabbit_live_probes.py` 抓当前已登录浏览器页。只有确认当前浏览器登录态可用时才使用，避免空状态覆盖旧证据。
- `--full-log-rebuild` 只在 Codex Manager DB 仍保留完整历史日志时使用。旧日志已清理后，必须保持默认增量模式。

线上每日刷新：

- 运行位置：Linux 服务器上的 `scheduler` 容器，入口脚本为 `scripts/run_server_refresh.py`。
- 定时：北京时间每天 04:00，由 `deploy/cron/refresh.cron` + `supercronic` 触发。
- 顺序：`fetch_public_content --announcements --multiplier-snapshots --skip-build` -> `scrape_missing_announcements --all-stations --write-probes`（仅凭据存在时）-> `build_site_data.py` -> `validate_refresh_outputs.py` -> `prune_audit_runs`。
- 缺少 `API_RELAY_SCRAPE_EMAIL/API_RELAY_SCRAPE_PASSWORD` 时走 degraded 模式：跳过登录态补抓，但公开快照、站点重建和校验仍需成功。
- 服务器手动触发命令：`docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec scheduler python scripts/run_server_refresh.py`。
- `.github/workflows/refresh-site-data.yml` 只保留 `workflow_dispatch`，不再保留 `schedule`，避免与服务器刷新双写。

## 增量日志规则

- 普通刷新读取 `data/codex-log-refresh-state.json`，只累计 Codex Manager DB 中尚未处理的新 `/v1/responses` 日志。
- cursor 以 `created_at` 为主，`id` 只作为同一时间戳内的排序辅助。
- 脚本会从 `cursor.createdAt - overlapWindow` 开始重读少量重叠日志，并用近期 `processedLogKeys` 去重，避免重叠窗口重复累计，也降低 SQLite `id` 清理后复用或延迟写入造成的漏统计风险。
- state 缺失时，脚本会用当前 DB 中仍存在的日志初始化累计状态。如果旧日志已被清理，初始化无法还原已删除历史。
- 旧日志可以在一次刷新成功、CSV diff 合理，并确认 `data/codex-log-refresh-state.json` 已提交或可靠备份后手动删除。刷新脚本不会自动删除 DB 日志。
- 如果某个公网 host 在已有 state 中没有累计指标，但当前 DB 仍保留它的旧日志，增量刷新会做一次历史回填；如果旧日志已清理，则只能从后续新日志开始累计。
- `--full-log-rebuild` 会忽略现有 state，从当前 DB 的全部 `/v1/responses` 日志重建累计指标。旧日志已删时不要使用，否则会把累计历史重建成不完整数据。

## 写盘保护规则

- 分组倍率和充值档位采用“非空整类替换”：只有当前刷新解析出对应类别的非空结构化数据时，才替换旧列表。
- 公告采用“非空合并去重”：抓到新公告时按 `id + publishedAt + content` 等线索合并；公告为空、失败、缺失或被风控阻断时，不删除旧公告。
- `_public_fetch` 写盘保守：`_status.json` 只有解析到非空公告才覆盖；`_pricing.*` 只有解析到非空分组或充值档位才覆盖。空抓取只进入运行报告并标记 `skipped/preserved_existing`。
- live probe 写盘保守：分组、充值和公告接口只有返回可用非空内容才覆盖旧成功结果；公告可维护 `mergedAnnouncements`，用于失败或空结果时保留历史公告。
- 登录失败、401、404、空列表、空结构、支付关闭、Turnstile、图形验证码、人机验证和风控阻断都只能记录真实状态，不能伪造分组、充值或公告，也不能覆盖旧成功证据。
- 如果站点已确认关闭且决定不再收录，必须同时移除识别规则和已有输入快照，避免旧日志或旧 probe 把它重新带回公开站点集合。

## 新站点发现与收录

- 每次 `audit_proxy_multipliers.py` 分析日志时都会扫描未分类公网 host，并写出 `request_log_station_candidates.csv`。
- 显式 `classify_station()` 规则优先。新站点进入正式质量统计前，需要补站点分类、公开 URL、展示名称和必要的费用证据。
- 私有供应商名只允许脱敏记录；公网 URL host 可以作为候选和质量统计 key。
- 本地回环地址、私有账号、临时测试服务和只存在于本地代理项目中的条目不能写入公开站点列表或前端 JSON。
- 同一中转站存在多个 API 域名时，是否 canonical 归并必须以当前项目收录规则为准。公开配置跳转、菜单链接、`supplier_name` 只能作为辅助线索，不能单独决定归并。
- `585016d3.u3u.dev`、`atomflow.vip` 这类日志发现的新公网 host 默认按独立站点处理，后续通过公开快照、登录态 probe 和人工核验补齐证据。

## 费用证据与采用倍率

- 正式费用行来源仅限结构化且可复核证据：登录态 API、公开结构化价格、官方外部店铺、人工截图核验或明确人工输入。
- 公告文本、自然语言描述、公开配置提示、不可复核截图和推测价格不能生成正式费用行。
- `audit_proxy_multipliers.py` 可以把详情页已归档的结构化 `groupMultipliers + rechargeTiers` 回灌成正式费用行，但仍必须经过来源 allowlist 和后续过滤。
- `scripts/build_site_data.py` 读取 live probe 时，会用结构化充值/套餐 `billingType` 推断站点类型；同时在存在分组证据时把有效充值/套餐计入已核验档位数。这个计数不补请求样本，也不会让无请求样本的站点进入正式排名。
- 采用倍率统一公式：`effective_multiplier = group_multiplier × rmbAmount ÷ usdAmount`；其中 `rmbAmount` 是人民币实付金额，`usdAmount` 是到账美元额度。
- sub2api/v1 钱包充值必须同时满足 `payment/config.enabled` 未关闭、checkout 未关闭、有支付方式、`balance_recharge_multiplier > 0` 且未 `balance_disabled`；否则只记录空/失败状态，不生成正式费用行。
- 正式排名和未排名最低倍率展示统一使用 Codex-like 分组口径：只排除明确 Claude/Anthropic/Sonnet/Opus/Haiku/Kiro/CC 或国产/公益模型分组，其余非空有效分组默认可作为 Codex-like 候选。
- 不能再按“全站最低已核验倍率”直接取值，否则容易把 Claude、国产、公益或异常渠道误作为 Codex 采用倍率。
- `multiplier_sanity_review.csv` 记录所有 `effective_multiplier < 0.001` 或 `>= 2` 的费用档位。刷新后必须核对这些档位的分组、充值换算、有效期和证据来源。
- `high_multiplier_review.csv` 只保留正式排名采用高倍率时的兼容报告，正常应为空。
- 费用证据齐全但请求样本为 0 的站点不会进入排行榜，只在收录站点和详情页中展示。
- `config/station_pricing_overrides.json` 的 `authoritative=true` 是强覆盖入口，会同时影响审计层 formal CSV 和详情页数据。只在浏览器或官方店铺已核对、而自动接口命名或换算容易误导时使用。

## 详情页数据缺口

- 详情页重点盘点三类证据：分组倍率、充值档位、公告。
- 缺分组或充值会影响正式成本口径；缺公告只影响详情页展示，不应伪造成空公告。
- sub2api/v1 probe 应尽量包含 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/payment/plans`、`/api/v1/announcements`。
- sub2api 的公告、分组、订阅和充值接口通常需要登录。公开 `/api/v1/settings/public` 只能补充配置，不替代登录态核验。
- 需要用户协助登录时，优先打开外部 Playwright 浏览器；Codex 内置浏览器适合自动核对，但不适合作为用户手动登录窗口。
- `window.__APP_CONFIG__` 中的 `payment_enabled` / `purchase_subscription_enabled` 只能作为站点类型提示，不能直接生成充值档位、核验档位或采用倍率。
- live probe 中已经结构化归一的充值档位可反推类型：同时存在 `permanent` 与月/周/日/季/年卡时为混合型；只有周期卡时为包月型；只有永久余额档位时为非包月型。已有明确 `stationTypeHint` 时不被空推断覆盖。
- 部分营销首页会把实际 DOM 作为 `\u003c...` 转义片段嵌在 HTML 中；公开快照解析需先解码再提取充值倍率、套餐卡片和外部店铺链接。
- 公开首页写明 `1 RMB = $1`、`¥1 = $5` 等钱包换算时，只能生成 `wallet topup sample ... RMB` 样本行；除非页面列出固定商品金额，否则不要伪造成一组固定充值档位。
- 官方外链小铺只暴露固定商品价格、没有展示到账额度时，按项目默认口径 `1 RMB = 1 USD` 生成外链兑换码档位，并在 `expiresRule` / `tierNotes` 标明这是 price-only 外链商品默认值；不要把站内 `/api/user/amount` 报价反向解释成到账 USD。
- 公开套餐卡片可作为详情页充值证据，但要保留套餐周期、总额度/每日额度和是否每日刷新，避免把月卡每日额度误算成单日总额度。
- 公告接口返回空列表、接口未抓取、接口需要登录、抓取失败和被验证码阻断要分开标注，避免把“暂无公告”和“没抓到公告接口”混为一谈。
- live probe 登录失败、401、空结构或缺详情数据时，`scripts/build_site_data.py` 可以回退读取 `../tabbit-audit-profile/pending-stations-api-probes.json` 中的旧成功结构化证据；这个回退只用于分组、充值和公告详情补全。
- 页面展示口径另见 `docs/frontend-display-notes.md`；`/ranking` 的未入榜原因应帮助区分缺请求样本、缺正式费用行、费用待人工复核和缺分组/充值证据。

## 2026-05-22/23 数据补抓复盘

- 未排名表新增“最低倍率”展示，只用于前端解释，不改变正式排名、评分、`effectiveMultiplier` 或 `rankedStationCount`。公式为 `Codex-like 最小非 0 分组倍率 × 实付人民币 ÷ 到账美元额度`；无法同时取得有效分组倍率和有效充值档位时显示 `-`。
- Codex-like 口径本轮改为排除式判断：分组名明确包含 Claude/Anthropic/Sonnet/Opus/Haiku/Kiro/CC 或国产/公益模型时排除；其他分组只要名称非空、倍率有限且大于 0，默认可参与 Codex-like 候选。这样可以覆盖 `vip`、线路名、企业专线等实际可供 Codex 使用但没有写明 `codex/openai/gpt/default` 的分组。
- Relay (`api.code-relay.com`) 的余额接口不再作为充值档位权威来源；公开订阅 plans 接口中的一次性充值档位才是本轮采用来源。当前一次性档位包含 `14.99/10`、`74.99/50`、`149.99/100`，最低倍率约 `1.499x`。`/api/status` 的 `7.3 RMB = 1 USD` 只保留为状态信息，不能覆盖订阅 plans 档位。
- Fushengyunsuan 与 KrillAI 之前算不出最低倍率，是因为旧规则只匹配 `codex/openai/gpt/default`。宽松 Codex-like 规则后，Fushengyunsuan 的 `vip`、`企业生图专线` 和 KrillAI 的线路分组可以正常命中；仍需排除 `公益`、Claude、Kiro、国产模型等明确非 Codex-like 分组。
- Nerverun (`api.nerverun.com`) 通过单站登录态 v1 probe 补齐分组、钱包档位、订阅套餐和公告。结构化证据显示同时存在永久余额和 10 天订阅套餐，因此类型为混合型；费用证据已具备，但 Codex Manager 请求样本为 0，所以未入榜原因应显示“缺请求样本”，不是“缺正式费用行”。
- Nerverun probe 覆盖 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/payment/plans`、`/api/v1/announcements`。可记录相对路径 `../tabbit-audit-profile/api.nerverun.com-live-auth-probe.json`，不要写入本机绝对路径、Cookie、token、邮箱或账号信息。

## 站点个案备忘

### 人工核验 / 官方店铺

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `Xiaoxin` | 余额充值商品 `49.99 RMB -> 1000 USD` 已核验；当前登录态分组接口返回 `余额用户（专用分组）` 倍率 `1.0`，正式采用倍率为 `0.04999`。 | 登录态 `/api/v1/groups/available`、官方外部店铺 `pay.ldxp.cn/shop/JZ9CUHL0`。 | 不能沿用旧人工输入里的 `1.3` 分组倍率；`verified_multiplier_inputs.csv` 的 v1 分组行应优先用当前 live probe 倍率。 | 若分组倍率再次变化，以登录态分组接口为准；外部店铺只负责核对充值金额和到账美元额度。 |
| `HelloCode` | 站内 `payment/config.enabled=false` 时不生成默认钱包费用行；已登录浏览器核验左侧“充值/订阅”嵌入官方链动小铺，可用 10/30/50/100 USD 兑换码商品生成正式费用行，当前采用 `codex-plus` 分组倍率 `0.1`。 | 登录态分组接口、官方外部店铺 `pay.ldxp.cn/shop/SAIS2N05`、充值页商品详情和支付确认弹窗。 | 不能只凭 `checkout-info` 的支付方式/倍率生成站内钱包档位；不能保存带 `token=`、`user_id=` 或邮箱的签名 URL。 | 复核外部店铺是否仍为 Hello-Code 已认证店铺，商品是否仍写明 1 元兑 1 刀并要求到站内兑换页兑换。 |
| `LumiBest` | 站内充值入口指向官方链动小铺 `pay.ldxp.cn/shop/WE9ZBUQG`；小铺只展示 `¥10/¥50/¥100` 商品价格、没有公开到账额度，按项目默认 `1 RMB = 1 USD` 生成外链兑换码档位。当前 Codex 采用分组应为 `codex`，倍率按 `0.1 * 10 / 10 = 0.1`，`MadeInChina` 因描述为国产大模型不参与 Codex-like 采用。 | 登录态 `/api/user/self/groups`、`/api/user/topup/info` 的 `topup_link`、官方外部店铺商品页。 | 不能把 `/api/user/amount?amount=10` 的 `73.00` 当成 `10 RMB -> 73 USD`；不能让 `MadeInChina`/国产大模型分组拉低 Codex 采用倍率。 | 如果后续小铺商品详情明确写到账额度，改用商品详情；否则继续按外链 price-only 默认 1:1。 |
| `PrintcapAI` | 可用人工截图核验费用行；当前 `GPT-MIX 1x`，`1 CNY = 2 USD`，采用倍率 `0.5`。 | 完整充值页截图、人工核验输入。 | 不能从公开配置或公告推断具体金额；登录态恢复前不要伪造公告。 | 若登录态 API 恢复，用结构化 API 重新复核截图结论。 |
| `VoAPI` | 已浏览器核验固定钱包充值档位，可生成正式费用行；当前按默认分组 `1x` 与最高折扣固定档位采用，采用倍率 `10650 / 2000 = 5.325`。 | 登录态 API 令牌页显示 `默认分组 (x1)`；钱包页固定档位显示到账美元额度，并在支付确认区显示人民币实付金额，例如 `￥71 -> 10 USD`、`￥337.25 -> 50 USD`、`￥10650 -> 2000 USD`。 | 不能把到账美元额度反写成人民币支付金额；不能使用 `test 50x` 作为默认 Codex 采用分组；不能提交真实付款。 | 若钱包页充值面额或折扣变化，更新 `config/station_pricing_overrides.json` 中显式档位；`rmbAmount` 必须是人民币实付金额，`usdAmount` 必须是到账美元额度。 |
| `laodog/dogcoding` | v1 支付配置关闭时使用官方外部店铺兑换码商品作为证据。 | 官方菜单指向的外部店铺商品。 | 不能在 `payment/config.enabled=false` 时生成默认钱包档位。 | 核对兑换码商品金额和到账美元额度，不按站内快捷充值处理。 |
| `zhishu.dev` | 登录态 v1 接口可补齐 `codex-自建` 分组和公告；站内支付配置关闭，但左侧“充值”嵌入的官方链动小铺已核验 5 个 Codex 商品，可生成充值/套餐档位。 | 登录态 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/announcements`、官方外部店铺 `pay.ldxp.cn/shop/CFUOS364/ek8gty`。 | 不能只凭 `balance_recharge_multiplier` 生成站内钱包档位；不能保存店铺签名 URL 参数、用户邮箱或 token。 | 用户协助登录后脚本仍抓不到时，可用浏览器直接识别官方店铺和页面内容，再反哺脚本/配置。外部店铺顶层登录态可见 10/20/50 USD 不限时额度和 Plus/Pro 包月商品；headless 直接访问可能 403 `http_bot_simple`。 |

### 公开结构化快照

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `FishXCode` | 已有结构化分组/充值证据，可生成费用行；请求样本为 0 时不入榜。 | 公开页面、公开结构化证据、详情页归档数据。 | 不能因为费用齐全就绕过请求样本门槛。 | 后续日志出现请求后，普通增量刷新即可参与排名。 |
| `claude360.xyz` | 公开 `/api/status` + `/api/pricing` 已足够生成正式费用行；请求样本为 0 时仍不入榜。 | 公开 status 的 `price/quota_per_unit` 换算、公开 pricing 的 `group_ratio`/分组结构。 | 不能因为费用齐全绕过请求样本门槛；不能把非结构化公告文本当费用来源。 | 当前 `1 RMB = 1 USD`，公开分组含 `Codex` 0.8；详情页证据可回灌 formal CSV。 |
| `cngpt.net` | 公开 `/api/status` + `/api/pricing` 已足够生成正式费用行；请求样本为 0 时仍不入榜；充值入口本轮暂不强行补抓。 | 公开 status 的 `price/quota_per_unit` 换算、公开 pricing 的默认分组结构。 | 不能因为费用齐全绕过请求样本门槛；不能把价格自然语言推断为固定套餐。 | 当前 `7.3 RMB = 1 USD`，`default` 分组按 Codex-like 可用分组处理；后续找到真实充值入口后再补固定档位。 |
| `fushengyunsuan.cn` | 公开 `/api/status` 与价格页可补分组、钱包换算和公告，可作为正式费用来源；宽松 Codex-like 规则后，`vip`、`企业生图专线` 等非 Claude/非国产分组可参与最低倍率计算。 | 公开 status、公开价格页、公告快照。 | 不能只因费用齐全绕过请求样本门槛；不能让 `公益` 分组拉低 Codex-like 最低倍率。 | 继续核对 `vip`/Codex 可用分组是否仍在公开价格页展示；最低倍率约 `0.052x`。 |
| `api.code-relay.com` | Relay 的一次性充值档位以公开订阅 plans 接口为权威；最低倍率约 `1.499x`。 | 公开 `/api/pricing` 分组倍率、公开 `/api/subscription/plans` 一次性充值档位、公告快照。 | 不能再用 `/api/status` 的 `7.3 RMB = 1 USD` 余额口径替代订阅 plans；不能把公告存在误认为已有请求样本。 | plans 应包含 `14.99/10`、`74.99/50`、`149.99/100`；普通刷新后核对 formal CSV 是否只在有请求样本时入榜。 |
| `api-slb.krill-ai.com` | 正确官网入口是 `https://www.krill-ai.com`；API 站点键仍保留 `api-slb.krill-ai.com`。当前可补齐分组和充值，公告接口真实为空；线路分组按 Codex-like 可用候选计算最低倍率。 | `config/station_url_overrides.json`、登录态 `/api/endpoint-settings/me`、公开 `/api/public/shop/products`、登录态 `/api/announcements/unread`。 | 不能继续用旧入口 404 结论；不能把空公告接口伪造成公告内容。 | Krill route/group 从 endpoint settings 归一化，商品从 shop products 归一化；`/api/announcements/unread` 空列表作为已核对状态，最低倍率约 `0.0395238x`。 |

### 登录态 v1 probe

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `MooseCloud` | 已有结构化分组/充值证据，可生成费用行；请求样本为 0 时不入榜。 | 登录态 probe、详情页归档数据。 | 不能只看 iframe 首页外壳就否定已有结构化证据。 | 浏览器核验真实页时注意主体可能在 iframe 中。 |
| `MuskAI` | 登录态订阅套餐可生成正式费用行；当前只把 `Codex订阅 1x` 与订阅套餐组合。 | 登录态订阅计划接口、详情页归档套餐证据。 | 不能把订阅套餐与 `Codex-Pro-Fast`、`Codex-Pro-Plus` 等按量分组交叉计算。 | 刷新后若套餐接口金额变化，先核对订阅页和套餐绑定分组，再更新详情证据。 |
| `guodongapi.site` | 使用登录态 v1 钱包倍率和 checkout-info 订阅档位。 | 登录态 v1 payment config、checkout-info。 | 不能沿用旧 `1x` 人工口径。 | 钱包充值按 `balance_recharge_multiplier=10`，订阅档位作为补充证据。 |
| `api.feifeimiao.top` | 登录态 v1 接口可补齐分组、钱包充值、订阅套餐和公告；当前支付倍率 `1 RMB = 5 USD`，充值手续费 `5%`。 | 登录态 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/payment/plans`、`/api/v1/announcements`。 | 不能保存 `/api/v1/auth/me` 用户资料；不能把月卡每日额度当单日套餐总额。 | 外部 Playwright 抓到 2 个分组、9 个套餐、9 条公告；probe 只保留结构化接口响应和脱敏元数据。 |
| `api.nerverun.com` | 登录态 v1 probe 已补齐分组、永久余额档位、10 天订阅套餐和公告；同时存在永久余额与订阅套餐，类型为混合型。当前费用证据已具备，但请求样本为 0，所以未入榜原因应为缺请求样本。 | 登录态 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/payment/plans`、`/api/v1/announcements`。 | 不能因为费用证据齐全就绕过请求样本门槛；不能把明确 Claude/Kiro 的分组当 Codex 采用分组；不能把新用户 `0.3` 专属权益泛化到普通分组。 | 余额档位按 `1 RMB = 1 USD`；订阅为 `20 RMB -> 80 USD`、专属倍率 `0.3`、有效期 10 天；公告时间为 `2026-05-10 22:09:43`，内容提到首充 20 元以上领取 `gptPro号池专属 0.3倍率`。 |
| `relayai.asia` | 登录态 v1 接口可补齐 `ChatGPT` 分组、钱包充值档位和公告；当前钱包换算 `1 RMB = 1 USD`，最低充值 `10 RMB`。 | 登录态 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/announcements`。 | 不能把模型 token 价格当充值档位；没有订阅套餐时只生成钱包快捷金额档位。 | 外部 Playwright 抓到 1 个分组、2 条公告，`/api/v1/payment/plans` 为空。 |
| `api.baobu.xyz` | 登录态 v1 支付 API 已恢复，可补齐 4 个分组和钱包充值档位；当前 `1 RMB = 1 USD`，充值手续费 `1%`，公告接口为空列表。 | 登录态 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/payment/plans`、`/api/v1/announcements`。 | 不能沿用旧支付关闭 probe；不能只凭旧空结果覆盖新成功证据。 | 当前分组为 `codex`、`闲鱼`、`Claude code-20x`、`Claude code-pro`；`quick_amounts` 生成 10 个钱包档位，实付人民币需计入 1% 手续费。 |

### 特殊平台 / 特殊入口

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `ICodex` | 公益站点，当前暂不要求补分组、充值档位和公告数据；已有少量请求样本也不代表具备费用证据。 | 真实页公开状态/维护信息、日志样本。 | 不能用请求样本、维护页或公告状态推断费用行。 | 暂时不作为缺口补抓目标；若后续站点提供结构化分组/充值，再按正常证据链补齐。 |
| `585016d3.u3u.dev` | 日志发现的新公网 host，按独立站点处理。 | Codex Manager 日志、公开快照、登录态补抓结果。 | 不能因 supplier 名称或菜单线索把它错误并入旧站点。 | 继续补分组、充值和公告；失败/空结果保留旧证据。 |
| `atomflow.vip` | 日志发现的新公网 host，按独立站点处理。 | Codex Manager 日志、公开 `/api/status`、`/api/pricing`、登录态补抓结果。 | 不能只凭旧站点规则跳过候选和质量统计。 | 保持新站点发现、公开快照、登录态 probe 的固定流程。 |
| `Euzhi` | 钱包金额来自实时换算采样。 | New API `/api/user/amount` 采样。 | 不能写成固定套餐档位。 | 文案展示为 `wallet topup sample ... RMB`，并保留采样口径。 |
| `Nexus` | 已从旧客服套餐切到站内钱包充值口径。 | 登录态分组、payment config、checkout-info。 | 不能继续使用旧 `VIP/PRO/MAX monthly` 硬编码口径。 | v1-like 的 `recharge_fee_rate` 要计入实付成本。 |

## 验证与排查清单

刷新后优先运行：

```powershell
python -m unittest tests/test_build_site_data.py
python audit_proxy_multipliers.py --help
python scripts/refresh_quality_rankings.py --help
python scripts/scrape_missing_announcements.py --help
npm run build
git status --short --branch
git diff --stat -- data/codex-log-refresh-state.json quality_metrics.csv composite_ranking_formal_*.csv data/site-data.json data/_public_fetch
```

文档或脚本口径变更后额外检查：

```powershell
rg -n "^#|^##" docs/data-refresh-notes.md
rg -n "codex-log-refresh-state|full-log-rebuild|request_log_station_candidates|multiplier_sanity_review" docs/data-refresh-notes.md
```

对账顺序：

1. Codex Manager DB：确认新日志是否存在，尤其是目标公网 host。
2. `quality_metrics.csv`：确认站点样本、成功率、耗时是否进入对应时间窗口。
3. `composite_ranking_formal_*.csv`：确认是否具备正式费用行并进入正式排名。
4. `data/site-data.json`：确认 `generatedAt`、`rankedStationCount`、`timeWindows`、详情证据和未入榜状态。
5. 本地 `/ranking` 与 `/stations/<station>`：确认采用倍率、分组、充值档位和未入榜原因。
6. 真实站点或官方店铺：对外部店铺、截图来源、异常倍率和高风险站点复核页面金额与文案。

常见误判：

- 正式排名大幅缩水时，先检查 `../tabbit-audit-profile/` 和 `verified_multiplier_inputs.csv` 是否丢失或只剩表头。
- 站点有详情页分组/充值/公告，不代表一定入榜；仍需请求样本和正式费用证据。
- 站点有请求样本但没有费用证据，只能留在未入榜表或待补证据状态。
- 质量 CSV 里样本为 0 是有效值，不能显示成无数据；只有质量行不存在才视为缺失。
- 只看页面或只看单个 CSV 容易误判。排查排名异常必须按 DB -> quality CSV -> formal CSV -> `site-data.json` -> 页面逐层对账。
- 纠正时段规则、站点分类、错误过滤、评分逻辑、别名归并或历史 DB 数据后，要重新生成 CSV、重建 `site-data.json`，再跑单测和构建。
