# 数据刷新维护手册

本文档记录 `api-relay-rank` 的数据刷新流程、证据采用规则和排查规则。README 只保留快速上手；数据刷新细节统一维护在这里。

## 核心原则

- 生成数据只能走脚本。不要手工编辑 `data/site-data.json`、`data/_public_fetch/`、质量 CSV 或排名 CSV。
- 失败和空结果不能覆盖旧成功证据。分组倍率、充值档位、公告、公开快照和 live probe 都遵守保旧规则。
- 缺口站点先用脚本补抓真实数据，再用浏览器核对页面；浏览器能看到但脚本抓不到时，优先修抓取入口、解析逻辑、归一化逻辑和文档，避免一次性手补 JSON。
- 正式排名门槛不放松：必须同时具备 Codex Manager 请求样本和可正式采用的费用证据。
- 凭据不入库。账号、密码、token、Cookie、浏览器会话和本地代理信息不能写入代码、文档、JSON 输出或日志。
- 本地工具、回环地址、私有账号键和临时代理服务不能进入公开站点池，只能留在内部排查链路。
- 周末全天归入非工作时段。刷新后要核对脚本口径、`site-data.json` 的 `timeWindows`、声明文案和页面展示。
- 正式综合榜单保留低样本站点，但同一时段内 `requests >= 10` 的站点永远优先于 `< 10` 的站点；低样本站点整体置后后再按分数、样本数和站点 key 排序。

## 数据来源与权威顺序

- Codex Manager `request_logs` 是质量样本来源，只统计 `/v1/responses`。站点后台数据不能补请求样本。
- `data/codex-log-refresh-state.json` 是日志累计指标的主存储，保存 cursor、三个时段累计指标、耗时样本、首包耗时样本和近期去重 key。旧日志清理后，历史排名只能从这个 state 延续。
- 公开快照位于 `data/_public_fetch/`，用于公开公告、公开价格、公开配置和可复核店铺信息。公开配置只能提示站点类型，不能凭自然语言或猜测生成正式费用行。
- 登录态证据位于 `../tabbit-audit-profile/`，是 sub2api/v1 分组、支付、公告详情的首选来源。结构化分组和充值/套餐同时抓到时，可计入已核验费用证据；仓库外目录可以作为相对路径引用，不要扩展成本机绝对路径。
- `verified_multiplier_inputs.csv` 用于人工核验输入。截图、官方店铺或浏览器人工核验可以进入这里，但必须可复核，且不能包含凭据。
- `data/site-data.json` 是前端主数据源，也是失败/空抓取时保留旧详情数据的基线之一；它不是人工编辑入口。

## 正式榜规则

- 正式榜必须同时具备 Codex Manager 请求样本和可正式采用的费用证据；后台分组、充值或公告证据不能替代请求样本。
- 排序顺序固定为：样本层级（`requests >= 10` 优先）-> `total_score` 降序 -> `requests` 降序 -> `station` 升序。低样本站点保留正式榜资格，但必须排在同一时段所有高样本站点之后。
- 费用覆盖和日志刷新后新增进入正式综合榜单的站点记录为：`150.242.246.223`、`icodex.pro`、`api.zicc.cc`、`www.thinkai.tv`、`www.haoyongai.xyz`、`api.code-relay.com`。多个新增站点样本数低于 10，必须受低样本置后规则约束。
- 排查正式榜数量变化时，先确认 formal CSV 是否已有费用行，再检查 `data/site-data.json` 的 `rankedStationCount` 与前端 `/ranking`；不要只看详情页证据是否完整。

## 刷新流程

本地普通刷新：

```powershell
npm run site:refresh-manual
```

`site:refresh-manual` 当前执行顺序：

1. 运行 `scripts/audit_proxy_multipliers.py`，做增量日志分析、新站点发现和排名 CSV 生成。
2. 运行 `scripts/build_site_data.py`，重建 `data/site-data.json`。
3. 运行 `scripts/fetch_public_content.py --announcements --multiplier-snapshots --skip-build --quiet`，刷新公开快照。
4. 如果存在 `API_RELAY_SCRAPE_EMAIL` 和 `API_RELAY_SCRAPE_PASSWORD`，运行 `scripts/scrape_missing_announcements.py --all-stations --write-probes`；缺凭据时跳过登录态补抓。
5. 运行 `scripts/refresh_invite_links.py --write`，用 `API_RELAY_INVITE_<STATION_KEY>_EMAIL/PASSWORD` 尝试补齐正式榜邀请链接；缺凭据或抓取失败时保留官网原链并生成 fallback 报告。
6. 再次运行审计脚本和 `scripts/build_site_data.py`，把新快照、probe 和邀请链接覆盖纳入最终输出。

可选命令：

```powershell
python scripts/refresh_quality_rankings.py --capture-live-probes
python scripts/refresh_quality_rankings.py --full-log-rebuild
```

- `--capture-live-probes` 会先调用 `scripts/capture_tabbit_live_probes.py` 抓当前已登录浏览器页。只有确认当前浏览器登录态可用时才使用，避免空状态覆盖旧证据。
- `--full-log-rebuild` 只在 Codex Manager DB 仍保留完整历史日志时使用。旧日志已清理后，必须保持默认增量模式。

## 邀请链接规则

- `config/station_invite_links.json` 是正式榜邀请链接配置，结构为 `{ "<station_key>": "<invite_url>" }`。该文件只保存公开邀请 URL，不保存账号、密码、Cookie 或 token。
- `scripts/build_site_data.py` 会把邀请链接覆盖到 `/ranking` 三个正式榜单的 `RankingRow.stationUrl`，并写入站点展示字段 `station.inviteUrl`，供详情页顶部按钮和未入榜收录列表的可点击站点入口使用。
- `station.url` 仍保留官网链接，用于站点基础资料、详情证据、公告来源、审计报告、SEO JSON-LD 和审计运行目标；这些数据来源不能改用邀请链接。
- `scripts/refresh_invite_links.py --write` 默认只处理 `work_hours`、`off_hours`、`all_hours` 任一正式榜中尚未配置邀请链接的站点；已配置站点会记录为 `skipped_configured` 并跳过，只有显式传 `--force` 才重新抓取。站点凭据通过 `API_RELAY_INVITE_<STATION_KEY>_EMAIL` 和 `API_RELAY_INVITE_<STATION_KEY>_PASSWORD` 提供，`<STATION_KEY>` 规则为站点 key 大写，非字母数字替换为 `_`。
- 新入榜站点没有邀请链接时不阻断刷新或发布；`scripts/build_site_data.py` 和 `scripts/validate_refresh_outputs.py` 会把它记录为 `fallback_official_url`，页面临时保留官网原链。默认报告位于 `.local-artifacts/station-invite-link-report.json`，服务器刷新会写到 `output/server-refresh-invite-links-summary.json`。
- 用户已确认 `new.sharedchat.cc`、`coolplay`、`muyuan.do`、`lumibest`、`icodex.pro`、`api.code-relay.com` 没有邀请链接。这些站点允许长期显示官网回退链接，`fallback_official_url` 在这里表示已确认无邀请链接或暂无可用邀请链接，不应伪装成待补抓错误。
- Playwright 人工补采按批执行：每批最多 10 个站点，逐个登录和检查，不并发打开大量标签；每批结束后更新 `config/station_invite_links.json`、关闭无用标签，并汇总 `captured`、`skipped_configured`、`fallback_official_url`、验证码/2FA/风控阻断和凭据失败站点。`sub2api` / `new-api` 优先查固定邀请、推广、返利、affiliate、referral、promotion、用户中心和充值页入口；`special` / `unknown` 需要人工辅助定位。
- `/statement` 保留邀请链接披露文案：部分中转站外链使用邀请链接，可能为测试账号带来少量额度奖励。这些额度将用于维持长期测试、扩大数据样本并持续更新排名；排名数据、评分和排序不受邀请链接影响，仅供参考。`/ranking` 正式综合排名标题区不再重复展示橙色邀请链接说明。

## 线上每日刷新

- 运行位置：Linux 服务器上的 `scheduler` 容器，入口脚本为 `scripts/run_server_refresh.py`。
- 定时：北京时间每天 04:00，由 `deploy/cron/refresh.cron` + `supercronic` 触发；cron 文件显式声明 `CRON_TZ=Asia/Shanghai`。
- 顺序：`fetch_public_content --announcements --multiplier-snapshots --skip-build` -> `scrape_missing_announcements --all-stations --write-probes`（仅凭据存在时）-> `refresh_invite_links.py --write`（仅邀请凭据存在时）-> `build_site_data.py` -> `validate_refresh_outputs.py` -> `prune_audit_runs`。
- `run_server_refresh.py` 会为 `build_site_data.py` 注入本次服务器刷新完成时的 `SITE_DATA_GENERATED_AT`，因此线上“数据生成于”表示最近一次服务器刷新写入时间。
- 缺少 `API_RELAY_SCRAPE_EMAIL/API_RELAY_SCRAPE_PASSWORD` 时走 degraded 模式：跳过登录态补抓，但公开快照、站点重建和校验仍需成功。
- 服务器手动触发命令：`docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec scheduler python scripts/run_server_refresh.py`。
- `.github/workflows/refresh-site-data.yml` 只保留 `workflow_dispatch`，不再保留 `schedule`，避免与服务器刷新双写。

## PostgreSQL 真源模式

- 前端只有在显式设置 `SITE_DATA_SOURCE=postgres` 且存在 `DATABASE_URL` 时才读取数据库；默认仍可按 JSON 模式本地开发和回滚。
- 生产页面读取 `site_data_snapshots` 中最新一条 `status='success'` 且 `payload` 非空的快照，保持前端数据结构与 `data/site-data.json` 一致。
- `/audit` 在 PostgreSQL 模式下优先读取 `station_audit_runs`，该表只保存审计历史 metadata、summary JSON、`report_path` 和 `source_path`；`report.md` 正文仍以 `data/_audit_runs/<station>/<model>/<run>/report.md` 为权威来源。
- `station_audit_runs` 主键为 `(station_key, model, run_id)`，`model` 使用目录 slug，summary JSON 中的 `model` 继续作为前端展示模型名。列表链接仍保持 `/api/audit-report?station=...&model=...&run=...`。
- `data/site-data.json` 不删除，继续作为导出备份、种子数据和显式回滚产物；不要把它当成生产默认真源。
- `SITE_DATA_ALLOW_FILE_FALLBACK=0` 时，数据库不可用会直接暴露错误，避免生产静默回退到过期 JSON 或 `_audit_runs` 文件列表。只有显式设置为 `1` 时，`site-data` 与 `/audit` 才允许在 DB 读取失败后回退文件。
- `SITE_DATA_MERGE_POSTGRES_BASE=1` 用于服务器刷新时继承上一条成功 DB snapshot 中已有的历史详情和证据，降低刷新时丢失 runtime-only 数据的风险。
- 生产 `site_data_snapshots` 可能包含仓库种子没有的 runtime-only 审计站点，因此线上 `stations[]` 数量可能高于仓库内 `data/site-data.json`。发布前应先把最新生产成功快照回填到仓库，或确认 deploy workflow 的站点数下降保护会拦截异常发布。
- deploy workflow 会记录重启前最新成功 snapshot 的站点数，并在重启后校验新 snapshot 站点数不得下降；只有显式设置仓库变量 `ALLOW_SITE_DATA_STATION_COUNT_DROP=1` 时才允许有意减少站点数。

### DB 模式服务器刷新顺序

1. `scripts/import_log_batches.py --fail-on-error` 导入 `LOG_INBOX_DIR` 中的脱敏日志包，成功后归档到 `LOG_ARCHIVE_DIR`。
2. `scripts/fetch_public_content.py --announcements --multiplier-snapshots --skip-build` 刷新公开公告和公开价格/倍率快照。
3. 若抓取凭据存在，执行 `scripts/scrape_missing_announcements.py --all-stations --write-probes`。
4. 若邀请凭据存在，执行 `scripts/refresh_invite_links.py --write`；缺失的正式榜邀请链接只记录为 `fallback_official_url`，不阻断发布。
5. 执行 `scripts/build_site_data.py` 重建 runtime `site-data.json`。
6. 执行 `scripts/validate_refresh_outputs.py` 校验输出，并生成邀请链接覆盖报告。
7. 执行 audit run 清理。
8. 执行 `scripts/publish_audit_history.py --delete-missing`，把仍被文件保留策略保留的成功审计历史同步到 `station_audit_runs`，并删除已被 prune 的 DB 行。
9. 执行 `scripts/publish_site_data_snapshot.py` 发布最新成功 DB snapshot。

### 审计历史回填与本地校验

```powershell
$env:SITE_DATA_SOURCE = "postgres"
$env:DATABASE_URL = "postgresql://api_relay_rank:api_relay_rank_local_password@127.0.0.1:15432/api_relay_rank"
python scripts/migrate_database.py
python scripts/publish_site_data_snapshot.py --source local-backfill
python scripts/publish_audit_history.py --delete-missing
```

审计历史 SQL 校验：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select count(*) as audit_runs, min(executed_at), max(executed_at) from station_audit_runs;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select overall_verdict, count(*) from station_audit_runs group by overall_verdict order by overall_verdict;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select station_key, model, run_id, executed_at, overall_verdict, report_path from station_audit_runs order by executed_at desc limit 10;"
```

### 审计运行完成后的 DB 模式同步

- `POST /api/station-audit/run` 完成审计归档后，会在 `site-data-rebuild` 锁内先执行 `scripts/build_site_data.py`，再执行 `scripts/publish_site_data_snapshot.py --source station-audit-run` 和 `scripts/publish_audit_history.py --delete-missing`。
- 这一步用于确保审计完成响应、`/audit` 历史列表、`/ranking` 未入榜站点和 `/stations/<station>` 详情都读取同一轮 runtime 结果。

## Windows Codex Manager 日志同步

- 任务名：`ApiRelayRankCodexLogSync`。
- 时间：本机 Windows 每天 `23:59:59`。
- 执行脚本：`scripts/run_codex_log_sync.ps1`。
- 安装/更新脚本：`scripts/install_windows_log_sync_task.ps1`。
- 上传目标：`github-actions-alerts-vps:/srv/api-relay-rank/log-inbox`。
- 导出内容：只包含脱敏后的 `/v1/responses` 白名单字段，不上传完整 Codex Manager DB，不保存账号、密码、token、Cookie 或邮箱。
- 手动同步命令示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_codex_log_sync.ps1 -UploadTarget "github-actions-alerts-vps:/srv/api-relay-rank/log-inbox"
```

### 04:00 后线上验收 SQL

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select batch_id, status, row_count, imported_at, archive_path, error from log_batches order by imported_at desc nulls last, created_at desc limit 5;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select count(*) as total_events, min(source_created_at), max(source_created_at), max(inserted_at) from request_log_events;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select run_id, status, started_at, finished_at, summary from analysis_runs order by started_at desc limit 5;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select id, run_id, status, generated_at, created_at, jsonb_array_length(payload->'stations') as stations from site_data_snapshots where status='success' order by created_at desc, id desc limit 5;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select count(*) as audit_runs, max(executed_at) as latest_audit_at from station_audit_runs;"
```

### 线上部署同步与审计历史

- VPS 部署时，app 容器启动会先运行 `scripts/seed_runtime_data.py`。当仓库版 `data/site-data.json` 的 `generatedAt` 晚于 runtime 数据卷时，它会同步仓库版主数据和 `_public_fetch` 到 runtime。
- app 和 scheduler 容器 seed 之后都必须继续运行 `scripts/rebuild_runtime_site_data.py`。该脚本使用 `site-data-rebuild` 锁，并把当前 runtime `site-data.json` 的 `generatedAt` 传给 `scripts/build_site_data.py`，这样可以保留本次数据生成时间，同时把 runtime `data/_audit_runs` 中的 audit-only 站点重新合入 `stations[]`。两个容器同时启动时，scheduler 不会在 app 重建后把 repo 版 `site-data.json` 留作最终状态。
- 这一步用于防止提交数据后的 deploy 把 VPS 审计历史站点从“未纳入正式排名的收录站点”和 `/stations/<station>` 详情页中冲掉。`data/_audit_runs` 仍只保留在线上数据卷，不提交进仓库。
- 如果 `/audit` 历史仍能看到记录，但点击站点详情出现 404，优先检查 app 容器启动日志里 `rebuild_runtime_site_data.py` 是否执行成功；临时恢复可在 app 容器内执行 `python scripts/rebuild_runtime_site_data.py`，再核对 `/stations/<audit-key>` 和 `/ranking`。
- 2026-05-25 的审计历史详情 404 事故就是这个问题：deploy seed 把仓库版 `site-data.json` 同步到 VPS runtime 后，没有把 runtime `_audit_runs` 重新合入，导致 `/audit` 仍有历史记录，但 `/stations/audit-right-codes` 和未入榜收录列表缺少对应站点。修复提交 `f6c3b2e` 后，已在线上核对 `/api/health`、`/stations/audit-right-codes` 和 `/ranking` 恢复；`/ranking` 是 ISR 页面，部署或 runtime 重建后必要时等待 5 分钟并请求两次再判断结果。

### PostgreSQL 上线追溯

- 本次上线 commit：`8a1497a feat: add local postgres ranking workflow`。
- GitHub Actions run：`26907601030`，部署成功。
- 上线前 VPS 备份：`/srv/api-relay-rank/backups/20260604-030923-pre-db-redeploy`。
- 本地备份：`.local-artifacts/backups/20260604-030837-pre-db-redeploy`。
- 本地 DB 作为上线基线同步到线上后，发布 `source=local-db-restore` 的 success snapshot；基线 `generatedAt=2026-06-04 01:59:27 +0800`，站点数 92，正式榜 `all=58 / work=50 / off=53`。
- app/scheduler 启动时会基于线上 runtime 再发布 startup snapshot，可能出现站点数高于本地基线的中间快照；最终以前端读取的最新 success snapshot 为准。
- 2026-06-04 04:00 自动刷新已验证跑通：`log_batches` 导入 `codex-log-20260603T194412Z-c1d55b54`，`row_count=20067`；`request_log_events=20067`；`analysis_runs` 最新 `server-refresh-20260603T200000Z-cf9987d6` 为 `success`。
- 04:00 自动刷新发布最新 snapshot：`generatedAt=2026-06-04 04:10:00 +0800`，站点数 94，正式榜仍为 `all=58 / work=50 / off=53`。
- `/api/health`、`/ranking`、`/audit`、`/statement`、`/stations/freemodel`、`/stations/585016d3.u3u.dev` 已在线上浏览器验收。
- PostgreSQL 容器 `api-relay-rank-postgres-1` 只服务本项目，不公开宿主机端口，不是公用 PostgreSQL；数据目录为 `/srv/api-relay-rank/postgres`。
- 服务器磁盘主要压力来自 Docker images 和 build cache；可安全运行 `docker builder prune -af` 与 `docker image prune -af`，不要运行带 `--volumes` 的 `docker system prune`。

## 站长公告 / 消息通知

- 站长公告固定抓取 GitHub issue `hwttop5/github-actions#1`；站内不再单独维护本地文案配置，也不再依赖 issue 正文 frontmatter。
- 页面运行时只读本地缓存，不在用户打开弹窗时直连 GitHub。缓存目录固定为 `data/_owner_announcement/`，其中：
  - `manifest.json` 保存标题、更新时间、正文和来源链接。
  - `assets/` 保存公告正文中图片下载后的本地副本。
- 同步脚本是 `scripts/refresh_owner_announcement.py`。刷新判断只看远端 issue 的 `updated_at` 与本地 `manifest.json` 里的 `updatedAt`；未变化时直接跳过，避免重复下载图片。
- 公告元数据口径固定为：`title = issue.title`、`updatedAt = issue.updated_at`、`content = issue.body`、`contentHtml = sanitize(issue.body_html)`。如果 issue 正文以 `---` 开头，也按普通 Markdown 原样保留，不再做 frontmatter 解析。
- 公告图片不直接引用 GitHub 外链。脚本会用 issue 的 `body_html` 解析实际渲染出来的图片地址，先下载到本地 `data/_owner_announcement/assets/`，再把 HTML 里的图片链接改写成站内 `/api/contact-ad/assets/...`。
- 本地 API `/api/contact-ad` 只负责读取 `manifest.json`；若本地缓存缺失、标题为空或正文/HTML 为空，则返回空公告，由前端进入空态展示。
- issue 正文为空时，不会触发首次自动弹窗；但右上角“消息通知”入口仍保留，用户手动打开时应看到“暂无公告”。
- `manifest.json` 和 `assets/` 都属于运行时缓存，不手工编辑；需要更新内容时，只改 GitHub issue 正文，再让脚本同步。

## 增量日志规则

- 普通刷新读取 `data/codex-log-refresh-state.json`，只累计 Codex Manager DB 中尚未处理的新 `/v1/responses` 日志。
- cursor 以 `created_at` 为主，`id` 只作为同一时间戳内的排序辅助。
- 脚本会从 `cursor.createdAt - overlapWindow` 开始重读少量重叠日志，并用近期 `processedLogKeys` 去重，避免重叠窗口重复累计，也降低 SQLite `id` 清理后复用或延迟写入造成的漏统计风险。
- state 缺失时，脚本会用当前 DB 中仍存在的日志初始化累计状态。如果旧日志已被清理，初始化无法还原已删除历史。
- 旧日志可以在一次刷新成功、CSV diff 合理，并确认 `data/codex-log-refresh-state.json` 已提交或可靠备份后手动删除。刷新脚本不会自动删除 DB 日志。
- 如果某个公网 host 在已有 state 中没有累计指标，但当前 DB 仍保留它的旧日志，增量刷新会做一次历史回填；如果旧日志已清理，则只能从后续新日志开始累计。
- `--full-log-rebuild` 会忽略现有 state，从当前 DB 的全部 `/v1/responses` 日志重建累计指标。旧日志已删时不要使用，否则会把累计历史重建成不完整数据。

Codex Manager 新日志增量更新：

- 默认执行 `npm run site:refresh-manual`，等价于增量分析 Codex Manager 新 `/v1/responses` 日志、重建 `site-data.json`、刷新公开快照、必要时登录态补抓，再跑一次增量分析和站点数据重建，让最新费率证据和排名 CSV 对齐。
- 如果用户指定从某个历史时间点开始补算，不要直接沿用当前 `HEAD` 的 state cursor；先找到该时间点对应的 `data/codex-log-refresh-state.json` 基线版本，只临时回放这个 state 文件，其他文件不回退，再按默认增量链路补算。
- 执行前先留证据：`git status --short --branch`、当前 state 的 `generatedAt` 和 `cursor.createdAt/id`、指定起点之后 Codex Manager DB 中可处理 `/v1/responses` 数量，以及其中符合脚本筛选条件的预估数量。
- 第一次补算后立即记录 state 摘要：`generatedAt`、`cursor.createdAt/id`、`lastRun.rowsSeen`、`lastRun.rowsAdded`、`lastRun.historicalBackfill`。最终保留本次 state 的最新 `generatedAt` 和 cursor，作为下次默认增量起点。
- Codex Manager 日志仍在持续写入时，最终校验前再跑一次 `scripts/audit_proxy_multipliers.py` 和 `scripts/build_site_data.py`，避免刷新过程中新增请求导致质量 CSV、正式排名 CSV 和 `data/site-data.json` 漂移。

## 写盘保护规则

- 分组倍率和充值档位采用“非空整类替换”：只有当前刷新解析出对应类别的非空结构化数据时，才替换旧列表。
- 公告采用“非空合并去重”：抓到新公告时按 `id + publishedAt + content` 等线索合并；公告为空、失败、缺失或被风控阻断时，不删除旧公告。
- `_public_fetch` 写盘保守：`_status.json` 只有解析到非空公告才覆盖；`_pricing.*` 只有解析到非空分组或充值档位才覆盖。空抓取只进入运行报告并标记 `skipped/preserved_existing`。
- live probe 写盘保守：分组、充值和公告接口只有返回可用非空内容才覆盖旧成功结果；公告可维护 `mergedAnnouncements`，用于失败或空结果时保留历史公告。
- 登录失败、401、404、空列表、空结构、支付关闭、Turnstile、图形验证码、人机验证和风控阻断都只能记录真实状态，不能伪造分组、充值或公告，也不能覆盖旧成功证据。
- 如果站点已确认关闭且决定不再收录，必须同时移除识别规则和已有输入快照，避免旧日志或旧 probe 把它重新带回公开站点集合。

## 新站点发现与收录

- 每次 `scripts/audit_proxy_multipliers.py` 分析日志时都会扫描未分类公网 host，并写出 `request_log_station_candidates.csv`。
- 显式 `classify_station()` 规则优先。新站点进入正式质量统计前，需要补站点分类、公开 URL、展示名称和必要的费用证据。
- 私有供应商名只允许脱敏记录；公网 URL host 可以作为候选和质量统计 key。
- 本地回环地址、私有账号、临时测试服务和只存在于本地代理项目中的条目不能写入公开站点列表或前端 JSON。
- 同一中转站存在多个 API 域名时，是否 canonical 归并必须以当前项目收录规则为准。公开配置跳转、菜单链接、`supplier_name` 只能作为辅助线索，不能单独决定归并。
- `585016d3.u3u.dev`、`atomflow.vip` 这类日志发现的新公网 host 默认按独立站点处理，后续通过公开快照、登录态 probe 和人工核验补齐证据。

## 费用证据与采用倍率

- 正式费用行来源仅限结构化且可复核证据：登录态 API、公开结构化价格、官方外部店铺、人工截图核验或明确人工输入。
- 公告文本、自然语言描述、公开配置提示、不可复核截图和推测价格不能生成正式费用行。
- `scripts/audit_proxy_multipliers.py` 可以把详情页已归档的结构化 `groupMultipliers + rechargeTiers` 回灌成正式费用行，但仍必须经过来源 allowlist 和后续过滤。
- `scripts/build_site_data.py` 读取 live probe 时，会用结构化充值/套餐 `billingType` 推断站点类型；同时在存在分组证据时把有效充值/套餐计入已核验档位数。这个计数不补请求样本，也不会让无请求样本的站点进入正式排名。
- 采用倍率统一公式：`effective_multiplier = group_multiplier × rmbAmount ÷ usdAmount`；其中 `rmbAmount` 是公式使用的实付金额数值，`usdAmount` 是到账美元额度。人民币仍直接写入 `rmbAmount`；USDC 等非人民币支付必须同时写 `paymentCurrency` / `paymentAmount`，避免详情页把真实支付币种误显示成人民币。
- sub2api/v1 钱包充值必须同时满足 `payment/config.enabled` 未关闭、checkout 未关闭、有支付方式、`balance_recharge_multiplier > 0` 且未 `balance_disabled`；否则只记录空/失败状态，不生成正式费用行。
- 正式排名和未排名最低倍率展示统一使用 Codex-like 分组口径：有 `codexEligible=false` 的分组先排除；名称包含 `福利` 的分组默认硬排除；明显 image-only / 生图专用分组默认排除，但有 `codexEligible=true` 等明确 Codex 可用证据时可保留；否则只排除明确 Claude/Anthropic/Sonnet/Opus/Haiku/Kiro/CC 或国产/公益模型分组，其余非空有效分组默认可作为 Codex-like 候选。
- sub2api 分组颜色是可用性证据：绿色分组按 Codex 可用处理并可写 `codexEligible=true`；橙色分组按 Claude Code 用途处理并写 `codexEligible=false`。如果登录态 API 只返回名称和倍率、没有颜色信息，不能猜颜色，只能保留名称规则或等待浏览器核验。
- 不能再按“全站最低已核验倍率”直接取值，否则容易把 Claude、国产、公益、福利、生图专用或异常渠道误作为 Codex 采用倍率。
- `multiplier_sanity_review.csv` 记录所有 `effective_multiplier < 0.001` 或 `>= 2` 的费用档位。刷新后必须核对这些档位的分组、充值换算、有效期和证据来源。
- `high_multiplier_review.csv` 只保留正式排名采用高倍率时的兼容报告，正常应为空。
- 费用证据齐全但请求样本为 0 的站点不会进入排行榜，只在收录站点和详情页中展示。
- `config/station_pricing_overrides.json` 的 `authoritative=true` 是强覆盖入口，会同时影响审计层 formal CSV 和详情页数据。只在浏览器或官方店铺已核对、而自动接口命名或换算容易误导时使用。
- 人工费用事实统一写入 `config/station_pricing_overrides.json`。截图、登录态页面和用户确认只作为可复核事实来源；正式榜采用值必须由配置覆盖和脚本重建进入派生数据。
- 当前结构化分组/充值优先于历史公告文本。`0.0075` 这类字符串如果只出现在旧公告或耗时小数里，不能当成当前分组倍率，也不能恢复为采用倍率。
- 证据优先级按可复核程度处理：登录态结构化 probe 和浏览器登录态页面最高；官方外部店铺、人工截图核验和公开结构化接口可作为费用证据；公告文本只作为上下文，不能单独生成当前费用行。
- `fetch_public_content.py` 当前没有单站过滤参数，刷新公开公告和倍率快照时只能跑全量；404、空列表、Turnstile 或登录失败必须记录真实状态，不能为了补齐页面而伪造分组、充值或公告。

## 详情页数据缺口

- 详情页重点盘点三类证据：分组倍率、充值档位、公告。
- 缺分组或充值会影响正式成本口径；缺公告只影响详情页展示，不应伪造成空公告。
- 当前正式 all-hours 榜为 `72` 个站点；仍缺数据的正式入榜站点只缺公告：`new.sharedchat.cc`、`freemodel`、`aicodelink`、`api.baobu.xyz`、`icodex.pro`、`www.thinkai.tv`、`crazyrouter.com`。分组倍率和充值档位在正式入榜集合中已有正式采用数据；已确认空公告不算缺口。
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

## 站点个案备忘

### 人工核验 / 官方店铺

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `Xiaoxin` | 余额充值商品 `49.99 RMB -> 1000 USD` 已核验；当前登录态分组接口返回 `余额用户（专用分组）` 倍率 `1.0`，正式采用倍率为 `0.04999`。 | 登录态 `/api/v1/groups/available`、官方外部店铺 `pay.ldxp.cn/shop/JZ9CUHL0`。 | 不能沿用旧人工输入里的 `1.3` 分组倍率；`verified_multiplier_inputs.csv` 的 v1 分组行应优先用当前 live probe 倍率。 | 若分组倍率再次变化，以登录态分组接口为准；外部店铺只负责核对充值金额和到账美元额度。 |
| `HelloCode` | 站内 `payment/config.enabled=false` 时不生成默认钱包费用行；已登录浏览器核验左侧“充值/订阅”嵌入官方链动小铺，可用 10/30/50/100 USD 兑换码商品生成正式费用行，当前采用 `codex-plus` 分组倍率 `0.1`。 | 登录态分组接口、官方外部店铺 `pay.ldxp.cn/shop/SAIS2N05`、充值页商品详情和支付确认弹窗。 | 不能只凭 `checkout-info` 的支付方式/倍率生成站内钱包档位；不能保存带 `token=`、`user_id=` 或邮箱的签名 URL。 | 复核外部店铺是否仍为 Hello-Code 已认证店铺，商品是否仍写明 1 元兑 1 刀并要求到站内兑换页兑换。 |
| `Happycode` | 充值页嵌入外部店铺，商品为 `5额度(0.06倍率)`、`30额度(0.06倍率)`、`100额度(0.06倍率)`，按 `1 RMB = 1 USD` 额度生成正式档位；当前唯一 Codex 分组为 `活动`，倍率 `0.06`。 | 浏览器登录态充值页、外部店铺卡片、站内 `/redeem` 兑换入口。 | 不能沿用旧公告中的 `0.04` 或旧 probe 里的倍率；不能保存外部店铺签名参数、账号邮箱或 token。 | 若店铺商品或站内分组变化，优先用登录态页面复核，再更新 `config/station_pricing_overrides.json` 并重建数据。 |
| `LumiBest` | 站内充值入口指向官方链动小铺 `pay.ldxp.cn/shop/WE9ZBUQG`；小铺只展示 `¥10/¥50/¥100` 商品价格、没有公开到账额度，按项目默认 `1 RMB = 1 USD` 生成外链兑换码档位。当前 Codex 采用分组应为 `codex`，倍率按 `0.1 * 10 / 10 = 0.1`，`MadeInChina` 因描述为国产大模型不参与 Codex-like 采用。2026-06-09 人工复核确认旧官网 `https://lumibest.store/` 已无法打开，历史公告曾提示迁移到 `https://lumibest.cc`。 | 登录态 `/api/user/self/groups`、`/api/user/topup/info` 的 `topup_link`、官方外部店铺商品页、用户人工复核。 | 不能把 `/api/user/amount?amount=10` 的 `73.00` 当成 `10 RMB -> 73 USD`；不能让 `MadeInChina`/国产大模型分组拉低 Codex 采用倍率；旧域名不可用时不能伪造邀请链接。 | 如果后续小铺商品详情明确写到账额度，改用商品详情；否则继续按外链 price-only 默认 1:1。后续应复核 `https://lumibest.cc` 是否已成为可用官网，再更新站点 URL。 |
| `PrintcapAI` | 可用人工截图核验费用行；当前 `GPT-MIX 1x`，`1 CNY = 2 USD`，采用倍率 `0.5`。 | 完整充值页截图、人工核验输入。 | 不能从公开配置或公告推断具体金额；登录态恢复前不要伪造公告。 | 若登录态 API 恢复，用结构化 API 重新复核截图结论。 |
| `VoAPI` | 已浏览器核验固定钱包充值档位，可生成正式费用行；当前按默认分组 `1x` 与最高折扣固定档位采用，采用倍率 `10650 / 2000 = 5.325`。 | 登录态 API 令牌页显示 `默认分组 (x1)`；钱包页固定档位显示到账美元额度，并在支付确认区显示人民币实付金额，例如 `￥71 -> 10 USD`、`￥337.25 -> 50 USD`、`￥10650 -> 2000 USD`。 | 不能把到账美元额度反写成人民币支付金额；不能使用 `test 50x` 作为默认 Codex 采用分组；不能提交真实付款。 | 若钱包页充值面额或折扣变化，更新 `config/station_pricing_overrides.json` 中显式档位；`rmbAmount` 必须是人民币实付金额，`usdAmount` 必须是到账美元额度。 |
| `api.zicc.cc` | 用户确认充值比例为 `1:1`；正式采用 `Codex Plus号池（推荐)` 倍率 `0.16`。`限时Team池` 倍率 `0.001` 因 `allow_messages_dispatch=false` 且为临时分组，不参与正式采用。 | 用户人工确认、登录态分组/充值页、`config/station_pricing_overrides.json` 权威覆盖。 | 不能把临时 Team 池或不可调度分组作为正式采用分组；不能用低价公告覆盖稳定 Codex Plus 口径。 | 若后续临时池恢复并成为长期可调度分组，先补可复核证据，再更新人工覆盖并重建榜单。 |
| `www.haoyongai.xyz` | 用户确认充值档位为 `1 RMB = 10 USD`；正式采用稳定 OpenAI/Codex 分组 `GPT` 倍率 `1`。公告里的临时福利价或临时福利分组不作为长期正式充值档位。 | 用户人工确认、登录态页面、`config/station_pricing_overrides.json` 权威覆盖。 | 不能把公告里的临时福利价当长期档位；不能用临时福利分组替代稳定 OpenAI/Codex 分组。 | 后续刷新继续优先采用稳定分组；若充值比例变化，先更新人工覆盖再重建派生数据。 |
| `api.wanlai.ai` | 官网入口为 `https://wanlai.ai`，API base 为 `https://api.wanlai.ai`。`/api/v1/payment/*` 返回 `404 page not found` 不阻断入榜，因为用户截图确认 `https://wanlai.ai/purchase` 充值页费用事实：正式采用 `OpenAi-官方订阅稳定渠道` 倍率 `1`，充值比例 `1 RMB ≈ 1 USD`，有效倍率 `1.0`。 | 用户截图确认的充值页、官网/API base 覆盖、`config/station_pricing_overrides.json` 权威覆盖。 | 不能因 payment API probe 404 判定无费用证据；不能采用横幅“低至 0.15”作为正式倍率，除非定位到具体长期正式渠道。 | 后续优先修正真实 API 探测；如页面正式渠道或充值比例变化，先更新人工覆盖再重建 CSV 与 `site-data.json`。 |
| `www.thinkai.tv` | 用户截图确认 `Codex（推荐）` 分组倍率 `1.2`，充值档位为 `25/50/100/200/500 USD` 分别实付 `12.5/25/50/100/250 RMB`，正式倍率为 `1.2 * 12.5 / 25 = 0.6`。 | 用户截图确认的分组倍率和充值页、`config/station_pricing_overrides.json` 权威覆盖。 | 不能用自动 `/api/user/amount` 采样返回值覆盖本轮权威口径；不能把截图之外的账号或浏览器状态写入公开数据。 | 后续若站内充值页或分组倍率变化，重新登录核验并更新人工覆盖。 |
| `codehub.qzz.io` | 2026-06-20 用户确认周报截图口径：分组可见 `GPT超低倍率 0.1x`、`GPT Pro 0.25x`、`GPT生图(Image2) 0.01x`、`GPT生图（Image2 4K） 1x`、`Kiro Claude 0.2x`；充值页可见余额充值 `$1/$10/$20/$50/$100/$500/$1000` 分别实付 `¥1/¥10/¥20/¥50/¥100/¥500/¥1000`，另有 `1天卡 ¥8.5`、`3天卡 ¥25`、`7天卡 ¥50`。本轮正式采用 `GPT超低倍率 | CodeHub wallet topup 1 USD`，有效倍率 `0.1`；天卡仅作详情展示。 | 用户周报截图确认的分组与充值页、`config/station_pricing_overrides.json` 权威覆盖。 | 不能猜测截图未完整展示的隐藏商品；不能把 `GPT生图(Image2)`、`GPT生图（Image2 4K）` 或 `Kiro Claude` 当作 Codex 正式采用分组；不能把天卡写入正式 adopted tier。 | 后续如页面展示出新的长期余额商品或分组倍率变化，先补截图或页面证据，再更新人工覆盖并重建数据。 |
| `kapibala.asia` | 用户截图确认钱包充值为 `¥3/6/15/30/60 -> $10/20/50/100/200`；订阅页可见 `Coding Plan Plus ¥78 -> $400`、`Coding Plan Pro(Plus x3) ¥220 -> $1200`、`Coding Plan Pro MAX(Plus x5) ¥360 -> $2000`；分组弹窗可见 `vip 1.1x` 与 `claude 1x`。本轮正式采用仍按用户确认锁定 `codex | Coding Plan Pro MAX(Plus x5)`，有效倍率 `0.18`。 | 用户截图确认的 `/wallet`、订阅页和分组弹窗、`config/station_pricing_overrides.json` 权威覆盖。 | 不能把截图里的 `vip 1.1x` 自动切成正式采用 `0.198`；不能回退到旧错误金额或旧日卡口径。 | 后续若继续沿用 `vip` 口径入榜，需先由用户确认 adopted tier 是否切到 `vip 1.1x`；当前仍以 `codex 1x` 作为正式采用分组。 |
| `ai.nexahub.one` | 用户截图确认 API 密钥页分组为 `Codex 余额计费 0.065x`、`ccmax满血（测试通过）0.7x`；充值页可见快捷金额 `10/20/50/100/200/500/1000/2000/5000`。本轮正式采用 `Codex 余额计费` 与 `NexaHub wallet topup 10 USD`，按页面可见 `1:1` 口径，采用倍率 `0.065`。 | 用户截图确认的 `/keys` 分组下拉和 `/purchase` 充值页、`config/station_pricing_overrides.json` 权威覆盖。 | 不能继续采用旧 `Team 团队订阅`；不能把登录态接口里的 `Codex 余额计费 0.8` 或 `balance_recharge_multiplier=15` 覆盖到本轮正式口径。 | 后续如要恢复接口倍率口径，必须先在页面支付确认区核实实付金额，不提交订单、不保存账号或付款信息。 |
| `laodog/dogcoding` | v1 支付配置关闭时使用官方外部店铺兑换码商品作为证据。 | 官方菜单指向的外部店铺商品。 | 不能在 `payment/config.enabled=false` 时生成默认钱包档位。 | 核对兑换码商品金额和到账美元额度，不按站内快捷充值处理。 |
| `zhishu.dev` | 用户周报反馈确认当前分组倍率均为 `0.3`；正式覆盖锁定 `codex-自建 0.3x`。站内支付配置关闭，但左侧“充值”嵌入的官方链动小铺已核验 5 个 Codex 商品，可生成充值/套餐档位，当前正式采用 `codex-自建 | Codex monthly Pro 500 USD quota`，有效倍率 `0.21`。 | 用户周报反馈、登录态 `/api/v1/groups/available`、`/api/v1/payment/config`、`/api/v1/payment/checkout-info`、`/api/v1/announcements`、官方外部店铺 `pay.ldxp.cn/shop/CFUOS364/ek8gty`、`config/station_pricing_overrides.json` 权威覆盖。 | 不能只凭 `balance_recharge_multiplier` 生成站内钱包档位；不能保存店铺签名 URL 参数、用户邮箱或 token；不能在登录态 probe 失效时回退到 `default 1x`。 | 后续若页面分组或外部小铺商品变化，先补用户截图或登录态页面证据，再更新权威覆盖并重建 CSV 与 `site-data.json`。外部店铺顶层登录态可见 10/20/50 USD 不限时额度和 Plus/Pro 包月商品；headless 直接访问可能 403 `http_bot_simple`。 |
| `x2app.top` | 站内“帮助和下单”指向官方链动小铺 `pay.ldxp.cn/shop/IU6GNW6R`；小铺公告写明 `x2app.top` 和全店 `x1`，商品包含不限时额度、日卡、周卡和 Pro 月卡。 | 公开配置 `custom_menu_items`、教程页 `https://x2app.top/jiaocheng.html`、链动小铺 `goodsList`、登录态 `/api/v1/groups/available`。 | 不能只因站内 `payment/config.enabled=false` 判定无充值；不能保存登录态凭据；Pro 月卡只作为可见套餐，采用倍率仍必须结合登录态 OpenAI 分组。 | 当前正式配置写入 `config/station_pricing_overrides.json`：Plus x1、Pro x1.5，最低采用 `2.8 RMB -> 35 USD` 日卡。 |
| `chaoye.xyz` | 站内 `/custom/47fd385f7ac9c619` 嵌入官方链动小铺 `pay.ldxp.cn/shop/chaoyeapi`；商品为 25/50/100/200 USD API 额度卡。 | 公开配置 `custom_menu_items`、链动小铺 `goodsList`、登录态 `/api/v1/groups/available`。 | `balance_low_notify_recharge_url` 的 `T2XWKG42` 当前店铺不可用，不能替代 `chaoyeapi`；Claude/Kiro/Gemini 分组不能作为 Codex 采用分组。 | 当前采用 OpenAI Plus/Pro 分组，最低采用 `Plus/Pro mixed pool x0.2` 与 25 USD 额度卡。 |
| `aitoken.dog` | 站内 `/custom/65e8232a27a8c9f1` 嵌入官方链动小铺 `pay.ldxp.cn/shop/8UTEMOWS`；商品为 10/20/30/50 USD 额度卡，文案写明实际按 `0.13` 计费。 | 公开配置 `custom_menu_items`、链动小铺 `goodsList`、登录态 `/api/v1/groups/available`。 | 站内支付配置关闭时不能生成默认钱包档位；Claude 分组不参与 Codex 采用。 | 当前采用 OpenAI `0.13` 分组与 1:1 额度卡，最低采用倍率 `0.13`。 |
| `pointfix.xyz` | `/purchase` 和公开配置指向官方链动小铺 `pay.ldxp.cn/shop/pointfix.xyz`；正式费用行只采纳 `pointfixAPI` 25/50/100/200 USD 额度卡。 | `/purchase`、公开配置 `purchase_subscription_url`、链动小铺 `goodsList`、登录态 `/api/v1/groups/available`。 | `GPT PLUS月卡成品号` 不是 API 额度商品；`1元20刀限量秒杀` 页面显示缺货，不进入正式费用行。 | 当前采用 Plus x0.15 / Pro x0.25 分组，最低采用 `Plus channel x0.15` 与 25 USD 额度卡。 |
| `api.apiwarrior.xyz` | 用户在登录态页面确认 `OpenAi-Plus` 倍率 `0.09x`、`OpenAi-Pro` 倍率 `0.3x`，两者可用于 Codex/OpenAI；充值页有 20/50/100 钱包充值选项，付款金额与选择金额一致。 | 登录态加款页、令牌分组选择器、用户人工截图/页面确认。 | `Claude full pool`、`Reverse Claude` 等 Claude-only 分组不能用于 Codex 正式采用；不能把截图中的账号或付款信息写入文档或数据。 | 正式采用 `OpenAi-Plus pool x0.09` 与 `Apiwarrior wallet topup 20 USD`；后续若分组或加款档位变化，需重新登录核验。 |
| `585016d3.u3u.dev` | 按独立 U3U 站点处理；公告 2 条，外部店铺兑换码档位可用，工作/非工作/全时段均有正式排名。 | Codex Manager 日志、登录态补抓、官方外部店铺、详情页线上核对。 | 不能因 supplier 名称或菜单线索并入旧站点；不能用风控失败或空抓取覆盖旧成功证据。 | 当前详情页需持续保留公告、Codex 余额分组和外部店铺永久额度/周卡/月卡档位。 |
| `ProdBbroot` | 当前只保留 `codex` 与 `openai` 两个 Codex 可用分组，正式榜采用 `openai` 倍率 `0.2`；公告外部卡网可见 `日卡`、`周卡`、`限时月卡`、`API额度$500`，其中只有 `API额度$500 ¥100 -> $500` 有明确额度并参与采用倍率，当前采用倍率 `0.04`。 | 浏览器登录态分组页、公告外部卡网 `pay.ldxp.cn/shop/47N31MWH`、站点公告。 | 不能恢复旧 `default`/Claude Code 分组；不能恢复旧 USDC/Solana `Starter (Weekly)` 档位；不能把无额度说明的日卡、周卡、月卡用于正式排名计算。 | 卡类商品只能以 `displayOnly=true` 写入人工 override 展示，不参与 adopted tier；`displayOnly` 不应放宽公开抓取解析，公开抓取缺 `usdAmount` 仍应视为不可生成正式费用行。 |

### 公开结构化快照

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `FishXCode` | 已有结构化分组/充值证据，可生成费用行；请求样本为 0 时不入榜。 | 公开页面、公开结构化证据、详情页归档数据。 | 不能因为费用齐全就绕过请求样本门槛。 | 后续日志出现请求后，普通增量刷新即可参与排名。 |
| `claude360.xyz` | 公开 `/api/status` + `/api/pricing` 已足够生成正式费用行；请求样本为 0 时仍不入榜。 | 公开 status 的 `price/quota_per_unit` 换算、公开 pricing 的 `group_ratio`/分组结构。 | 不能因为费用齐全绕过请求样本门槛；不能把非结构化公告文本当费用来源。 | 当前 `1 RMB = 1 USD`，公开分组含 `Codex` 0.8；详情页证据可回灌 formal CSV。 |
| `cngpt.net` | 公开 `/api/status` + `/api/pricing` 已足够生成正式费用行；请求样本为 0 时仍不入榜；充值入口本轮暂不强行补抓。 | 公开 status 的 `price/quota_per_unit` 换算、公开 pricing 的默认分组结构。 | 不能因为费用齐全绕过请求样本门槛；不能把价格自然语言推断为固定套餐。 | 当前 `7.3 RMB = 1 USD`，`default` 分组按 Codex-like 可用分组处理；后续找到真实充值入口后再补固定档位。 |
| `fushengyunsuan.cn` | 公开 `/api/status` 与价格页可补分组、钱包换算和公告，可作为正式费用来源；正式采用优先使用长期 Codex 可用分组，当前采用 `vip` 约 `0.08x`，`生图临时用，但是不一定安全=0.01` 只作为详情证据展示，不参与正式采用或未入榜最低倍率。 | 公开 status、公开价格页、公告快照。 | 不能只因费用齐全绕过请求样本门槛；不能让 `公益`、福利或生图临时分组拉低 Codex-like 最低倍率；不能恢复旧的 `0.0075` 异常分组。 | 继续核对 `vip`/Codex 可用分组是否仍在公开价格页展示；当前刷新以最新分组为准，最低倍率约 `0.08x`。 |
| `api.code-relay.com` | 2026-06-10 用户确认账号被封禁，无法登录补抓；当前人工口径为分组倍率 `1`，充值比例未找到，暂按 `1 RMB = 1 USD`。 | 用户人工确认、旧公开快照和归档 probe；当前以 `config/station_pricing_overrides.json` 为权威费用覆盖。 | 不能继续沿用旧 public plans `1.499x` 结论作为当前正式口径；不能用封禁账号状态伪造登录态充值证据。 | 后续若找到账单或充值页证据，先更新人工覆盖和本文档，再重建 CSV 与 `site-data.json`。 |
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
| `zhima` | 前 20 复核确认详情页必须展示正式排名采用的钱包充值口径；当前保留正式采用 `cx_free | wallet topup 10 RMB`，详情页补齐 `10/20/50/100/200/500/1000 RMB -> 同额 USD` 钱包档位。 | 正式排名采用项、登录态 v1 支付配置和详情页一致性复核、`config/station_pricing_overrides.json` 详情覆盖。 | 不能让详情页只展示订阅套餐而缺失正式排名采用的钱包充值档位。 | 若后续登录态页面显示不同钱包金额或充值比例，先更新详情覆盖，再重建 CSV 与 `site-data.json`。 |

### 特殊平台 / 特殊入口

| 站点 | 当前结论 | 可用证据来源 | 不能做什么 | 下次刷新注意点 |
| --- | --- | --- | --- | --- |
| `ICodex` | 用户确认 `icodex.pro` 是公益站；若日志样本满足正式榜单门槛，以免费额度成本 `0` 参与正式综合榜单。 | 用户人工确认、真实页公开状态、日志样本、旧 probe 归档。 | 不能用请求样本、维护页、公告状态或登录页倒推收费费用行；不能反复触发价格/充值页补抓。 | 若后续站点不再公益或提供收费充值页，先更新公益规则和人工覆盖，再重建榜单。 |
| `MuyuanDo` | 用户确认 `muyuan.do` 是公益站；详情页应展示 `Codex 免费公益线路` 和 `签到免费额度`，与正式排名免费口径一致。 | 用户人工确认、公益站规则、`config/station_pricing_overrides.json` 详情覆盖。 | 不能用公开 `/api/status` 的 `0.05 RMB = 1 USD` 付费换算覆盖公益免费详情；不能反复作为充值页补抓目标。 | 若后续站点不再公益或开放收费充值页，先更新公益规则和人工覆盖，再重建榜单。 |
| `code.pndot.com` | 用户确认 `https://code.pndot.com` 当前打不开；继续作为不可用站点处理，不再作为自动或人工补抓目标。历史日志和旧 probe 只保留为归档证据。 | 2026-06-10 人工确认、历史日志、旧 probe。 | 不能用旧 probe、历史公告或请求样本生成新的费用行；不能让自动补抓把该站重新带入缺口队列。 | 若站点恢复并重新开放页面，再按新站点恢复流程补公开快照、登录态 probe 和费用证据。 |
| `lpgpt.us` | 用户确认账号被封禁，无法登录抓取；不使用封禁登录态推断新费用证据，保留既有公开/归档证据。 | 用户人工确认、既有公开/归档证据。 | 不能用封禁账号状态伪造登录态分组、充值或公告证据。 | 后续只有账号恢复或公开证据更新时再刷新费用证据。 |
| `freemodel` | 特殊平台，已抓取登录态账单、用量、充值和日志接口的脱敏结构化摘要；未发现公告接口。正式榜中 all/work/off 均正常显示。 | 登录态 dashboard API：auth/me、billing、billing invoices、usage、logs；线上 `/stations/freemodel` 核对。 | 不能把用户资料、账单敏感字段、token、Cookie 或邮箱写入 probe；不能伪造公告。 | 公告状态保留为 `public_missing`；费用证据以 Pro/Max 月卡和自定义余额充值结构化摘要为准。 |
| `585016d3.u3u.dev` | 日志发现的新公网 host，按独立站点处理。 | Codex Manager 日志、公开快照、登录态补抓结果。 | 不能因 supplier 名称或菜单线索把它错误并入旧站点。 | 继续补分组、充值和公告；失败/空结果保留旧证据。 |
| `atomflow.vip` | 日志发现的新公网 host，按独立站点处理。 | Codex Manager 日志、公开 `/api/status`、`/api/pricing`、登录态补抓结果。 | 不能只凭旧站点规则跳过候选和质量统计。 | 保持新站点发现、公开快照、登录态 probe 的固定流程。 |
| `Euzhi` | 钱包金额来自实时换算采样。 | New API `/api/user/amount` 采样。 | 不能写成固定套餐档位。 | 文案展示为 `wallet topup sample ... RMB`，并保留采样口径。 |
| `Nexus` | 已从旧客服套餐切到站内钱包充值口径。 | 登录态分组、payment config、checkout-info。 | 不能继续使用旧 `VIP/PRO/MAX monthly` 硬编码口径。 | v1-like 的 `recharge_fee_rate` 要计入实付成本。 |

## 验证与排查清单

刷新后优先运行：

```powershell
python -m unittest tests/test_build_site_data.py
python scripts/audit_proxy_multipliers.py
python scripts/build_site_data.py
python scripts/validate_refresh_outputs.py --skip-scrape-validation
python scripts/audit_proxy_multipliers.py --help
python scripts/refresh_quality_rankings.py --help
python scripts/scrape_missing_announcements.py --help
npm run build
git diff --check
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

提交数据后线上对账：

1. `/api/health`：确认 `generatedAt` 已变成本次刷新时间。
2. `/ranking`：确认正式排名数量、未纳入正式排名的收录站点和重点站点未异常缩水；ISR 页面必要时等待并请求两次。
3. `/stations/<station>`：抽查本次新增、未入榜和 audit-only 站点详情页是否返回 200，尤其是 `/audit` 历史里可点击的站点。

提交前排除 `.codex-tmp/`、本地截图、构建缓存和无关本地改动。常规数据刷新只应包含 `data/codex-log-refresh-state.json`、`quality_metrics.csv`、`composite_ranking_formal_*.csv`、`data/site-data.json`、`data/_public_fetch/*` 以及明确需要同步的审计输出；文档同步只提交对应文档。

常见误判：

- 正式排名大幅缩水时，先检查 `../tabbit-audit-profile/` 和 `verified_multiplier_inputs.csv` 是否丢失或只剩表头。
- 站点有详情页分组/充值/公告，不代表一定入榜；仍需请求样本和正式费用证据。
- 站点有请求样本但没有费用证据，只能留在未入榜表或待补证据状态。
- 质量 CSV 里样本为 0 是有效值，不能显示成无数据；只有质量行不存在才视为缺失。
- 只看页面或只看单个 CSV 容易误判。排查排名异常必须按 DB -> quality CSV -> formal CSV -> `site-data.json` -> 页面逐层对账。
- 纠正时段规则、站点分类、错误过滤、评分逻辑、别名归并或历史 DB 数据后，要重新生成 CSV、重建 `site-data.json`，再跑单测和构建。

### 人工登录与上线确认记录

- `api.apiwarrior.xyz`：用户在登录态浏览器确认加款页 20/50/100 钱包充值选项可用，付款金额与选择金额一致；`OpenAi-Plus=0.09x`、`OpenAi-Pro=0.3x` 可用于 Codex/OpenAI；`Claude full pool=1.2x` 与 `Reverse Claude=0.4x` 为 Claude-only，不能用于 Codex 正式排名。正式采用 `OpenAi-Plus pool x0.09` 与 `Apiwarrior wallet topup 20 USD`。
- `freemodel`：登录态抓取账单、用量、充值和日志结构化摘要；未发现公告接口，公告状态记录为 `public_missing`；线上详情页已核对 all/work/off 正式排名与档位展示。
- `585016d3.u3u.dev`：按独立 U3U 站点处理，公告 2 条，外部店铺永久额度、周卡和月卡档位可用；线上详情页已核对。
- `x2app.top`、`chaoye.xyz`、`aitoken.dog`、`pointfix.xyz`：充值入口来自官方外部页面或后台 iframe 外链；这些外链是官方证据入口，不应因站内支付配置关闭而判定无充值。
- `icodex.pro`：2026-06-10 用户进一步确认是公益站；可按免费额度参与正式榜单，但不再作为价格/充值页补抓目标。
- `code.pndot.com`：2026-06-10 用户确认 `https://code.pndot.com` 当前打不开，继续不作为自动或人工补抓目标。


### 2026-06-20 错误上报处理

- `codehub.qzz.io`：补充并修正本地权威费用覆盖。截图确认 5 个分组事实，其中 Codex 正式采用分组更新为 `GPT超低倍率 0.1x`；余额充值可见 `$1/$10/$20/$50/$100/$500/$1000` 对应实付 `¥1/¥10/¥20/¥50/¥100/¥500/¥1000`，另有 `1/3/7` 天卡只作详情展示。正式采用 `GPT超低倍率 0.1x + CodeHub wallet topup 1 USD`。
- `kapibala.asia`：保持正式采用口径为 `0.18`。继续采用钱包 `¥3/6/15/30/60 -> $10/20/50/100/200`，补充月卡 `Coding Plan Pro(Plus x3) ¥220 -> $1200` 和 `Coding Plan Pro MAX(Plus x5) ¥360 -> $2000`，记录截图事实 `vip 1.1x`，但正式采用仍锁定 `codex | Coding Plan Pro MAX(Plus x5)`。
- `ai.nexahub.one`：保持无订阅口径。截图显示“暂无可用订阅套餐”，继续采用页面可见 1:1 钱包充值与 `Codex 余额计费 0.065x`，不恢复 `Team 团队订阅` 或 `balance_recharge_multiplier=15` 旧口径。

### aiapi1.cc.cd / dc API

- 2026-06-18 用户截图确认：`https://aiapi1.cc.cd` 是 `dc API` 公益站，令牌分组 `free` 倍率 `0.1x`。
- 详情页采用 `签到免费额度`，正式采用有效倍率为 `0`；不要把免费额度写成付费充值档位。
- 公告截图事实：邀请一人送 30 刀、永久不收费，并特别标注邀请/受邀金额有效期只有一周且每周金额重置为 0。
- 证据来源为用户截图确认的 `/console` 系统公告和 `/console/token` 令牌分组、公开 pricing 快照 `group_ratio.free=0.1`、Codex Manager 日志样本；不能保存账号、token、Cookie、余额、密钥或付款信息，不能伪造公告接口数据。
- 若后续站点不再公益或开放收费充值页，先更新公益规则和人工覆盖，再重建 CSV 与 `site-data.json`。

### freeapi.514179.xyz / Free API

- 2026-06-18 用户截图确认：`https://freeapi.514179.xyz` 是公益站，无充值档位和页面可见倍率。
- 详情页采用 `免费公益额度`，正式采用有效倍率为 `0`；结构化 `免费公益线路` 分组只用于让公益免费额度进入正式排名，不代表页面存在付费倍率。
- 本轮请求样本来自 `data/codex-log-refresh-state.json` 的旧样本状态，不使用 `--full-log-rebuild`，避免当前 SQLite 已查不到的 3 个旧样本被清空。
- 若后续站点开放付费充值页或展示真实分组倍率，先更新人工覆盖，再重建 CSV 与 `site-data.json`。

### api.feng.cx / Feng API

- 2026-06-18 用户截图确认：`api.feng.cx` 分组包含 `codex 0.08x`、`codex纯血PRO池 0.15x`、`default 1x`、`claude max 1.3x`、`image2分组 1x`。
- 正式费用按平时 `1:1` 充值口径，记录为 `wallet topup sample 10 RMB -> 10 USD`；页面未列固定商品金额，不伪造成固定充值档位。
- 618 活动公告中的 `0.9r 一刀`、满额折扣和活动截止时间只作为公告事实保留，不进入正式费用计算。
- 正式采用 `codex | wallet topup sample 10 RMB`，采用倍率 `0.08`。

### api.bluesminds.com / Bluesminds

- 2026-06-18 用户截图确认：`api.bluesminds.com` topup 页展示 `10 Days Plan $25`、`20 days $50`、`unlimted plan $60`、`60 days $120`、`3 day claude paid $24 / $800` 等套餐；分组页显示 `default 1x`，通知指向 Telegram。
- 本轮只采用截图套餐事实，不回退到旧公开 status 的 `1 RMB = 2 USD credit` 口径。
- 用户确认正式采用 `10 Days Plan $25`；截图未给独立额度字段，本轮按价格型订阅 `25 -> 25` 口径计算。
- `$0` 试用/赠送套餐和 `claude-paid` 套餐不得作为 Codex 正式采用项。
