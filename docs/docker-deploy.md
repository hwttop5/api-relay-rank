# Docker 一键部署

本文档对应当前仓库的服务器部署方案：`app + scheduler + postgres` 三服务接入外部 `shared_proxy` 网络，由共享 Caddy 统一处理 `80/443`。服务器自身负责每日数据刷新，PostgreSQL 是前端生产主数据源。

## 目录与前提

- 服务器已安装 Docker Engine 与 Compose v2。
- 域名 A 记录已指向服务器，且共享 Caddy 所在主机已放行 `80/443`。
- 服务器运行时目录固定为 `/srv/api-relay-rank`。
- 当前生产依赖 Compose 内置 PostgreSQL；日志 inbox、归档、runtime 数据和数据库都走服务器本地持久化目录。
- 外部 Docker 网络 `shared_proxy` 必须已存在，并由共享 Caddy 连接。

先准备运行时目录：

```bash
sudo mkdir -p \
  /srv/api-relay-rank/data \
  /srv/api-relay-rank/probes \
  /srv/api-relay-rank/postgres \
  /srv/api-relay-rank/log-inbox \
  /srv/api-relay-rank/log-archive \
  /srv/api-relay-rank/backups
```

## 环境变量

复制环境变量模板并填写：

```bash
cp deploy/.env.example deploy/.env
```

至少需要修改：

- `APP_DOMAIN`
- `NEXT_PUBLIC_SITE_URL`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `SITE_DATA_SOURCE=postgres`
- `SITE_DATA_ALLOW_FILE_FALLBACK=0`
- `SITE_DATA_MERGE_POSTGRES_BASE=1`
- `LOG_INBOX_DIR=/runtime/log-inbox`
- `LOG_ARCHIVE_DIR=/runtime/log-archive`
- `NEXTAUTH_URL`
- `NEXTAUTH_SECRET`
- `GITHUB_ID`
- `GITHUB_SECRET`
- `SMTP_HOST`
- `SMTP_FROM`
- `ERROR_REPORT_DIGEST_TO`

可选抓取凭据：

- `API_RELAY_SCRAPE_EMAIL`
- `API_RELAY_SCRAPE_PASSWORD`
- `API_RELAY_SCRAPE_BOSSCLAW_EMAIL`
- `API_RELAY_SCRAPE_BOSSCLAW_PASSWORD`

不提供抓取凭据时，scheduler 会进入 degraded 模式：公开快照与 `site-data.json` 仍刷新，登录态补抓会跳过并写日志，但整次任务不会失败。

用户反馈功能需要 GitHub OAuth 与 SMTP。GitHub OAuth 回调地址为 `https://<your-domain>/api/auth/callback/github`。错误上报截图保存在 `/srv/api-relay-rank/data/_user_uploads/error-reports`，每周五 22:00 北京时间由 scheduler 执行 `scripts/send_weekly_error_report_digest.py`，将未汇总过的错误上报发送到 `ERROR_REPORT_DIGEST_TO`。
GitHub Actions 部署需要配置仓库 Secrets：`AUTH_GITHUB_ID`、`AUTH_GITHUB_SECRET`、`NEXTAUTH_SECRET`、`SMTP_HOST`、`SMTP_FROM`、`ERROR_REPORT_DIGEST_TO`；workflow 会把 `AUTH_GITHUB_ID` / `AUTH_GITHUB_SECRET` 写成应用运行时需要的 `GITHUB_ID` / `GITHUB_SECRET`。缺少必填项时 workflow 会失败，避免用户反馈功能半启用上线。

PostgreSQL 只服务本项目。容器 `api-relay-rank-postgres-1` 只在 `api-relay-rank_default` 网络内提供 `5432/tcp`，不向宿主机公开端口，数据目录固定为 `/srv/api-relay-rank/postgres`。核心表包括 `site_data_snapshots`、`ranking_rows`、`quality_metrics`、`evidence_snapshots` 和 `station_audit_runs`；审计报告正文仍保存在 `/srv/api-relay-rank/data/_audit_runs`。

## 启动

首次部署和后续更新统一使用：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

容器启动时会自动执行 runtime 自检/播种：

- 如果 `/runtime/data/site-data.json` 不存在，或镜像内 `data/site-data.json` 的 `generatedAt` 更新，就从镜像内初始数据复制。
- 如果 `/runtime/data/_public_fetch` 不存在或为空，就从镜像内初始公开快照复制。
- `/runtime/data/_audit_runs`、`/runtime/data/_locks`、`/runtime/tabbit-audit-profile` 会自动创建。
- 当 `SITE_DATA_SOURCE=postgres` 时，`app` 和 `scheduler` 会先运行数据库迁移，再重建 runtime `site-data.json`，发布一条 `site_data_snapshots` success snapshot，并执行 `scripts/publish_audit_history.py --delete-missing` 同步审计历史索引。
- `app` 和 `scheduler` 在完成启动数据流程后，都会额外执行一次 `python scripts/refresh_owner_announcement.py || true`，预热本地公告缓存；公告同步失败不会阻塞容器启动。

## 日常运维

健康检查：

```bash
curl -fsS https://<your-domain>/api/health
```

手动触发一次服务器刷新：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec scheduler python scripts/run_server_refresh.py
```

查看日志：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f app scheduler postgres
```

手动触发一次公告同步：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec scheduler python scripts/refresh_owner_announcement.py
```

查看最新数据库快照：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select id, run_id, status, generated_at, created_at from site_data_snapshots order by created_at desc, id desc limit 5;"
```

查看日志同步导入状态：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select batch_id, status, row_count, imported_at, archive_path, error from log_batches order by imported_at desc nulls last, created_at desc limit 5;"
```

查看审计历史入库状态：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select count(*) as audit_runs, max(executed_at) as latest_audit_at from station_audit_runs;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select station_key, model, run_id, overall_verdict, report_path from station_audit_runs order by executed_at desc limit 5;"
```

## 刷新与审计行为

- 站长公告与站点主数据刷新分离：公告检查是高频轻量任务，站点主数据仍保持每天 `04:00` 的完整刷新链路。
- scheduler 固定使用 `supercronic`，时区固定 `Asia/Shanghai`，计划为每天 `04:00`。
- `deploy/cron/refresh.cron` 里额外有一条每 5 分钟任务：`python scripts/refresh_owner_announcement.py`。脚本只比较远端 issue `updated_at` 与本地缓存 `updatedAt`；没有变化时不会重复拉取正文和图片。
- `deploy/cron/refresh.cron` 每周五 22:00 运行错误上报周报脚本；发送成功后会把本批报告标记为已汇总，失败时保留为待发送。
- DB 模式刷新顺序固定为：
  1. 从 `LOG_INBOX_DIR` 导入脱敏 Codex Manager log batch 到 `log_batches` 和 `request_log_events`。
  2. `fetch_public_content --announcements --multiplier-snapshots --skip-build`
  3. `scrape_missing_announcements --all-stations --write-probes`（仅凭据存在时）
  4. `build_site_data.py`
  5. `validate_refresh_outputs.py`
  6. `prune_audit_runs`
  7. `publish_audit_history.py --delete-missing` 同步 `station_audit_runs`，删除已被文件保留策略清理的 DB 行。
  8. 发布最新 `site_data_snapshots.status='success'`。
- 公告缓存保存在运行时卷 `/srv/api-relay-rank/data` 下的 `_owner_announcement/`，因此 `manifest.json` 和 `assets/` 会随容器重启保留，不需要在每次打开弹窗时重新抓 GitHub 图片。
- `GITHUB_TOKEN` 是可选优化项。存在时脚本优先走带 `Authorization: Bearer ...` 的 GitHub API；缺失时允许回退到公开 API，必要时再尝试 `gh api`。
- `POST /api/station-audit/run` 仍保持公开，但会同时受以下限制：
  - SSRF 拦截与 DNS 解析后地址校验
  - 应用层单并发审计锁
  - 共享 Caddy 层限流与请求体限制
- 在 DB 模式下，单次审计成功归档后会重建 runtime `site-data.json`，再发布 `source=station-audit-run` 的站点快照并同步 `station_audit_runs`。`/audit` 历史列表读取 DB，点击报告仍读取 `_audit_runs` 中的 `report.md`。

## 备份与恢复

`Deploy to VPS` workflow 每次同步代码前会自动创建一次预部署备份，目录格式为 `/srv/api-relay-rank/backups/<UTC>-pre-<short_sha>/`。自动备份包含：

- `/opt/stacks/api-relay-rank` 应用目录压缩包（排除 `.git`、`.next`、`.next-dev`、`node_modules`）
- `/opt/stacks/api-relay-rank/deploy/.env` 的独立副本，权限收紧到 `600`
- `/srv/api-relay-rank/data`、`probes`、`log-inbox`、`log-archive` 的运行时压缩包
- `api_relay_rank` 的 `pg_dump -Fc` 逻辑备份
- 当前可导入 `_audit_runs/**/summary.json` 数量，用于部署后比对 `station_audit_runs`

同一个 workflow 在重启 Docker stack 后会强制校验：`schema_migrations.version=6`、`station_audit_runs` 行数、最新成功 `site_data_snapshots`、`/api/health`、`/api/auth/providers`、`/audit`、`/ranking`、`/stations/freemodel` 和最新审计报告链接。任一关键检查失败时 workflow 会失败，不继续标记部署成功。

部署前至少备份：

- `/opt/stacks/api-relay-rank`
- `/opt/stacks/api-relay-rank/deploy/.env`
- `/srv/api-relay-rank/data`
- `/srv/api-relay-rank/probes`
- `/srv/api-relay-rank/postgres`
- `/srv/api-relay-rank/log-inbox`
- `/srv/api-relay-rank/log-archive`

如果 postgres 容器可用，再额外导出一份逻辑备份：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  pg_dump -U api_relay_rank -d api_relay_rank -Fc > /srv/api-relay-rank/backups/postgres-before-change.dump
```

从本地 dump 恢复线上数据库时，先停止 `app` 和 `scheduler`，恢复完成后再启动，并确认最新 `site_data_snapshots` 与 `station_audit_runs` 与预期一致。

恢复后建议执行：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select id, run_id, status, generated_at, created_at from site_data_snapshots where status='success' order by created_at desc, id desc limit 3;"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec -T postgres \
  psql -U api_relay_rank -d api_relay_rank \
  -c "select count(*) as audit_runs, min(executed_at), max(executed_at) from station_audit_runs;"
```

## Windows 日志同步

本机 Windows 任务 `ApiRelayRankCodexLogSync` 每天 `23:59:59` 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_codex_log_sync.ps1 -UploadTarget "github-actions-alerts-vps:/srv/api-relay-rank/log-inbox"
```

脚本只导出脱敏后的 `/v1/responses` 白名单字段，生成 zip 后上传到服务器 `log-inbox`。04:00 服务器刷新会导入 zip 并移动到 `log-archive`。

## Docker 磁盘清理

当前服务器还运行多个项目容器。`api-relay-rank` 的 PostgreSQL 是本项目独立容器，不是公用数据库，但服务器上存在 Caddy、Qdrant 等 Docker volume。

安全清理旧镜像和构建缓存：

```bash
docker builder prune -af
docker image prune -af
```

不要使用：

```bash
docker system prune -a --volumes
```

`--volumes` 可能删除其他项目仍需要的 Docker volume。清理前后建议查看：

```bash
docker system df
df -h /data
docker ps
```
