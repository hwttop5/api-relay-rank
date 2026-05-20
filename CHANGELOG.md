# Changelog

## v0.1.2 - 2026-05-20

1. 统一站点品牌与页面文案为“AI中转站监视者”，同步优化综合排名/安全审计入口命名与 README 指引。
2. 升级站点刷新链路：新增站点级备用抓取账号能力，补充登录阻断处理约束，并完善数据重建与校验说明。
3. 刷新全站公开快照与 `data/site-data.json`，同步更新站点详情证据与正式榜单展示数据。

### English Notes

1. Unified site branding and page copy as “AI Relay Monitor”, including clearer naming for ranking/audit entries and README guidance.
2. Upgraded the refresh pipeline with station-level fallback scrape accounts, stricter blocked-login handling rules, and clearer rebuild validation notes.
3. Refreshed all public snapshots and regenerated `data/site-data.json` with updated station evidence and ranking display data.

## v0.1.1 - 2026-05-19

1. 将站点展示数据刷新升级为每天北京时间 04:00 的单次 GitHub Actions 自动任务。
2. 新增全站登录态 probe 抓取与刷新结果校验，覆盖分组倍率、充值档位、公告证据和敏感信息泄露检查。
3. 刷新 Nexus 及全站公开快照数据，并补充自动刷新链路、Secrets 要求和非 README 维护文档。

### English Notes

1. Upgraded display-data refreshes to a single daily GitHub Actions run at 04:00 Beijing time.
2. Added all-station live-auth probe capture and refresh validation for group multipliers, recharge tiers, announcements, and secret-leak checks.
3. Refreshed Nexus and public station snapshots, with updated non-README maintenance docs for the automation and required secrets.

## v0.1.0 - 2026-05-17

1. 首次发布 `api-relay-rank`，提供 AI 中转站综合排名、站点详情与公开公告聚合能力。
2. 补齐公开倍率、价格快照与站点数据整理流程，支持站点信息持续更新。
3. 提供基于 `Vercel + GitHub Actions` 的部署方案，便于后续持续发布与维护。

### English Notes

1. First public release of `api-relay-rank` with ranking views, station details, and announcement aggregation.
2. Added public multiplier and pricing snapshot pipelines to keep station data up to date.
3. Included a `Vercel + GitHub Actions` deployment flow for ongoing releases and maintenance.
