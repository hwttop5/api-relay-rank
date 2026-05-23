# AI中转站监视者

`api-relay-rank` 是一个面向中文用户的 AI 中转站观察站点，核心页面是 `/ranking`、`/audit`、`/statement` 和 `/stations/[station]`。

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
