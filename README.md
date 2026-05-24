# AI中转站监视者

`api-relay-rank` 是一个面向中文用户的 AI 中转站监视站点，用公开快照、可用性观察和安全审计结果，帮助用户快速了解各中转站的排名表现、倍率档位、公告动态和基础风险。你可以在 `/ranking` 查看综合排名，在 `/audit` 发起本地黑盒审计，在 `/statement` 了解排名口径，并通过 `/stations/[station]` 查看单个站点详情。

## 快速开始

要求：

- Node.js 20+
- Python 3.11+

```powershell
npm install
pip install -r requirements.txt
npm run dev
```

生产构建：

```powershell
npm run build
```

## 文档入口

- Docker 服务器部署：[`docs/docker-deploy.md`](docs/docker-deploy.md)
- 数据刷新与证据口径：[`docs/data-refresh-notes.md`](docs/data-refresh-notes.md)

## 常用命令

```powershell
npm run site:data
npm run site:announcements
npm run site:tiers
npm run site:audit
npm run site:refresh-manual
npm run site:jobs
```
