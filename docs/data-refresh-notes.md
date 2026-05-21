# 数据刷新维护手册

本文档记录 `api-relay-rank` 的数据刷新流程、证据采用规则和排查经验。README 只保留快速上手；数据刷新细节统一维护在这里。

## 核心原则

- 生成数据只能走脚本。不要手工编辑 `data/site-data.json`、`data/_public_fetch/`、质量 CSV 或排名 CSV。
- 失败和空结果不能覆盖旧成功证据。分组倍率、充值档位、公告、公开快照和 live probe 都遵守保旧规则。
- 正式排名门槛不放松：必须同时具备 Codex Manager 请求样本和可正式采用的费用证据。
- 凭据不入库。账号、密码、token、Cookie、浏览器会话和本地代理信息不能写入代码、文档、JSON 输出或日志。
- 本地工具、回环地址、私有账号键和临时代理服务不能进入公开站点池，只能留在内部排查链路。
- 周末全天归入非工作时段。刷新后要核对脚本口径、`site-data.json` 的 `timeWindows`、声明文案和页面展示。

## 数据来源与权威顺序

- Codex Manager `request_logs` 是质量样本来源，只统计 `/v1/responses`。站点后台数据不能补请求样本。
- `data/codex-log-refresh-state.json` 是日志累计指标的主存储，保存 cursor、三个时段累计指标、耗时样本、首包耗时样本和近期去重 key。旧日志清理后，历史排名只能从这个 state 延续。
- 公开快照位于 `data/_public_fetch/`，用于公开公告、公开价格、公开配置和可复核店铺信息。公开配置只能提示站点类型，不能凭自然语言或猜测生成正式费用行。
- 登录态证据位于 `../tabbit-audit-profile/`，是 sub2api/v1 分组、支付、公告详情的首选来源。仓库外目录可以作为相对路径引用，不要扩展成本机绝对路径。
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

- GitHub Actions workflow：`.github/workflows/refresh-site-data.yml`。
- 定时：北京时间每天 04:00，对应 cron `0 20 * * *`。
- 顺序：公开公告/价格快照 -> 全站登录态 probe -> `scripts/build_site_data.py` -> `scripts/validate_refresh_outputs.py` -> 如有 diff 则提交 `data/site-data.json` 和 `data/_public_fetch`。
- 线上登录态补抓只读取 GitHub Actions Secrets 注入的环境变量；不提交 probe 文件、token、cookie 或密码。
- Vercel 只在 Actions 提交数据变更后部署，不负责定时抓取。

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
- 登录失败、401、404、空结构、Turnstile、图形验证码、人机验证和风控阻断都只能记录状态，不能覆盖旧成功证据。
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
- 采用倍率统一公式：`effective_multiplier = group_multiplier × rmb_amount ÷ usd_amount`。
- 正式排名优先使用 Codex 口径分组中的最小非 0 倍率，其中 `default` 视为 Codex 可用分组；缺少明确 Codex/default 分组时，才回退到最低非 Claude 分组。
- 不能再按“全站最低已核验倍率”直接取值，否则容易把非 Codex/异常渠道误作为采用倍率。
- `multiplier_sanity_review.csv` 记录所有 `effective_multiplier < 0.001` 或 `>= 2` 的费用档位。刷新后必须核对这些档位的分组、充值换算、有效期和证据来源。
- `high_multiplier_review.csv` 只保留正式排名采用高倍率时的兼容报告，正常应为空。
- 费用证据齐全但请求样本为 0 的站点不会进入排行榜，只在收录站点和详情页中展示。
- `config/station_pricing_overrides.json` 的 `authoritative=true` 是强覆盖入口，会同时影响审计层 formal CSV 和详情页数据。只在浏览器或官方店铺已核对、而自动接口命名或换算容易误导时使用。

## 详情页数据缺口

- 详情页重点盘点三类证据：分组倍率、充值档位、公告。
- 缺分组或充值会影响正式成本口径；缺公告只影响详情页展示，不应伪造成空公告。
- sub2api/v1 probe 应尽量包含 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/payment/plans`、`/api/v1/announcements`。
- sub2api 的公告、分组、订阅和充值接口通常需要登录。公开 `/api/v1/settings/public` 只能补充配置，不替代登录态核验。
- `window.__APP_CONFIG__` 中的 `payment_enabled` / `purchase_subscription_enabled` 只能作为站点类型提示，不能直接生成充值档位、核验档位或采用倍率。
- 公告接口返回空列表、接口未抓取、接口需要登录、抓取失败和被验证码阻断要分开标注，避免把“暂无公告”和“没抓到公告接口”混为一谈。
- live probe 登录失败、401、空结构或缺详情数据时，`scripts/build_site_data.py` 可以回退读取 `../tabbit-audit-profile/pending-stations-api-probes.json` 中的旧成功结构化证据；这个回退只用于分组、充值和公告详情补全。
- 页面展示口径另见 `docs/frontend-display-notes.md`；`/ranking` 的未入榜原因应帮助区分缺请求样本、缺正式费用行、费用待人工复核和缺分组/充值证据。

## 站点个案备忘

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `HelloCode` | 可生成钱包费用行；本次正式采用 `codex-plus` 钱包充值，采用倍率 `0.1`。 | 登录态 `/api/v1/payment/checkout-info`、分组接口和详情页结构化证据。 | 不能仅因公开配置 `payment_enabled=false` 判定钱包不可用。 | 继续确认 `balance_disabled=false`、支付方式存在、`balance_recharge_multiplier` 有效。 |
| `PrintcapAI` | 可用人工截图核验费用行；当前 `GPT-MIX 1x`，`1 CNY = 2 USD`，采用倍率 `0.5`。 | 完整充值页截图、人工核验输入。 | 不能从公开配置或公告推断具体金额；登录态恢复前不要伪造公告。 | 若登录态 API 恢复，用结构化 API 重新复核截图结论。 |
| `VoAPI` | 当前费用待人工复核，不进入正式排名采用结果。 | 自定义充值样本 `10 USD -> 71 RMB`、公告/页面可见信息。 | 不能把自定义充值样本当固定充值档位；不能绕过验证码。 | 需要人工浏览器确认固定充值档位和人民币实付金额后再改状态。 |
| `ICodex` | 有少量请求样本，但缺分组倍率和充值档位结构化证据。 | 真实页公开状态/维护信息、日志样本。 | 不能用请求样本、维护页或公告状态推断费用行。 | 等登录态 probe 或人工浏览器核验补齐分组与充值后再刷新。 |
| `FishXCode` | 已有结构化分组/充值证据，可生成费用行；请求样本为 0 时不入榜。 | 公开页面、公开结构化证据、详情页归档数据。 | 不能因为费用齐全就绕过请求样本门槛。 | 后续日志出现请求后，普通增量刷新即可参与排名。 |
| `MooseCloud` | 已有结构化分组/充值证据，可生成费用行；请求样本为 0 时不入榜。 | 登录态 probe、详情页归档数据。 | 不能只看 iframe 首页外壳就否定已有结构化证据。 | 浏览器核验真实页时注意主体可能在 iframe 中。 |
| `585016d3.u3u.dev` | 日志发现的新公网 host，按独立站点处理。 | Codex Manager 日志、公开快照、登录态补抓结果。 | 不能因 supplier 名称或菜单线索把它错误并入旧站点。 | 继续补分组、充值和公告；失败/空结果保留旧证据。 |
| `atomflow.vip` | 日志发现的新公网 host，按独立站点处理。 | Codex Manager 日志、公开 `/api/status`、`/api/pricing`、登录态补抓结果。 | 不能只凭旧站点规则跳过候选和质量统计。 | 保持新站点发现、公开快照、登录态 probe 的固定流程。 |
| `laodog/dogcoding` | v1 支付配置关闭时使用官方外部店铺兑换码商品作为证据。 | 官方菜单指向的外部店铺商品。 | 不能在 `payment/config.enabled=false` 时生成默认钱包档位。 | 核对兑换码商品金额和到账美元额度，不按站内快捷充值处理。 |
| `guodongapi.site` | 使用登录态 v1 钱包倍率和 checkout-info 订阅档位。 | 登录态 v1 payment config、checkout-info。 | 不能沿用旧 `1x` 人工口径。 | 钱包充值按 `balance_recharge_multiplier=10`，订阅档位作为补充证据。 |
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

