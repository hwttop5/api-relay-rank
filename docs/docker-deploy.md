# Docker 一键部署

本文档对应当前仓库的服务器部署方案：`Traefik + app + scheduler` 三服务，`80/443` 由 Traefik 直接接管，证书自动签发和续期，服务器自身负责每日数据刷新。

## 目录与前提

- 服务器已安装 Docker Engine 与 Compose v2。
- 域名 A 记录已指向服务器，且 `80/443` 已放行。
- 服务器运行时目录固定为 `/srv/api-relay-rank`。
- 首版不依赖 Redis、数据库或消息队列，锁与归档都走本地文件系统。

先准备运行时目录：

```bash
sudo mkdir -p /srv/api-relay-rank/data /srv/api-relay-rank/probes /srv/api-relay-rank/traefik
sudo touch /srv/api-relay-rank/traefik/acme.json
sudo chmod 600 /srv/api-relay-rank/traefik/acme.json
```

## 环境变量

复制环境变量模板并填写：

```bash
cp deploy/.env.example deploy/.env
```

至少需要修改：

- `APP_DOMAIN`
- `ACME_EMAIL`
- `NEXT_PUBLIC_SITE_URL`

可选抓取凭据：

- `API_RELAY_SCRAPE_EMAIL`
- `API_RELAY_SCRAPE_PASSWORD`
- `API_RELAY_SCRAPE_BOSSCLAW_EMAIL`
- `API_RELAY_SCRAPE_BOSSCLAW_PASSWORD`

不提供抓取凭据时，scheduler 会进入 degraded 模式：公开快照与 `site-data.json` 仍刷新，登录态补抓会跳过并写日志，但整次任务不会失败。

## 启动

首次部署和后续更新统一使用：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

容器启动时会自动执行 runtime 自检/播种：

- 如果 `/runtime/data/site-data.json` 不存在，就从镜像内初始数据复制。
- 如果 `/runtime/data/_public_fetch` 不存在或为空，就从镜像内初始公开快照复制。
- `/runtime/data/_audit_runs`、`/runtime/data/_locks`、`/runtime/tabbit-audit-profile` 会自动创建。

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
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f traefik app scheduler
```

## 刷新与审计行为

- scheduler 固定使用 `supercronic`，时区固定 `Asia/Shanghai`，计划为每天 `04:00`。
- 刷新顺序固定为：
  1. `fetch_public_content --announcements --multiplier-snapshots --skip-build`
  2. `scrape_missing_announcements --all-stations --write-probes`（仅凭据存在时）
  3. `build_site_data.py`
  4. `validate_refresh_outputs.py`
  5. `prune_audit_runs`
- `POST /api/station-audit/run` 仍保持公开，但会同时受以下限制：
  - SSRF 拦截与 DNS 解析后地址校验
  - 应用层单并发审计锁
  - Traefik `1 req / 60s / IP` 限流
  - Traefik `inFlightReq=1`
  - Traefik `maxRequestBodyBytes=16384`

## 切换注意事项

- 服务器方案启用后，应暂停 `.github/workflows/refresh-site-data.yml` 的 `schedule`，避免与服务器刷新双写。
- 现仓库已保留 `workflow_dispatch`，只移除了定时触发。
- `/audit` 页面与 `/api/audit-report` 继续公开；如果匿名审计被滥用，应优先调紧 Traefik 中间件，不要先改站点数据结构。
