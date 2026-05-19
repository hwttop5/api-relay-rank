# AI中转站监视者

`api-relay-rank` 是一个面向中文用户的 AI 中转站观察站点，用于汇总和展示中转站的正式综合排名、站点详情、公开公告，以及公开可见的分组倍率和充值档位信息。

项目采用 `Next.js 15 + React 19 + TypeScript` 构建前端页面，并配合 Python 脚本整理站点相关数据，最终生成页面所需内容。

## 核心功能

- 综合排名页：支持工作时段、非工作时段、全时段切换，并支持按站点类型和排序方式重新排列。
- 未纳入正式排名站点列表：展示已收录但未进入正式榜单的站点。
- 站点详情页：展示单站排名快照、最近公告、分组倍率表和充值档位表。
- 公开公告聚合：抓取并展示站点公开公告内容。
- 倍率 / 价格快照归档：抓取并整理公开可见的倍率和价格信息。
- 安全审计页：输入中转站 API 地址和临时 API Key，选择模型后触发本地黑盒审计；已收录站点自动匹配，未收录站点按域名归档。
- 审计结果展示：详情页展示最新审计结论、风险级别、关键风险项、步骤摘要和原始报告入口；审计结果不影响首页正式排名排序。
- 定时任务编排：支持公告与倍率数据的定时刷新。

## 技术栈

- 前端：Next.js 15
- UI：React 19 + TypeScript
- 数据处理：Python
- 部署：Vercel + GitHub Actions

## 本地启动

要求：

- Node.js 20 或更高版本
- Python 3.11 或更高版本

安装与启动：

```powershell
npm install
pip install -r requirements.txt
npm run dev
```

生产构建：

```powershell
npm run build
```

## 常用命令

```powershell
npm run dev
npm run build
npm run start
npm run site:data
npm run site:announcements
npm run site:tiers
npm run site:audit
npm run site:refresh-manual
npm run site:jobs
```

## 提交规范

本项目使用 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 约束提交信息。

首次拉取仓库后执行一次 `npm install`，会自动安装 Husky Git hooks；之后每次 `git commit` 都会校验提交信息格式。
