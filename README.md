# 中转站监视者

`api-relay-rank` 是一个中文站点，用来展示 AI 中转站的正式排名、全部档位倍率表和公开公告。

## 本地启动

```powershell
cd api-relay-rank
npm install
npm run dev
```

## 常用命令

```powershell
npm run site:data
npm run site:announcements
npm run site:tiers
npm run site:refresh-manual
npm run site:jobs
```

## 提交规范

本项目使用 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 约束提交信息，格式如下：

```text
<type>[optional scope]: <description>
```

常用类型包括 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`、`ci`、`build`、`perf`、`style` 和 `revert`。

示例：

```text
feat(ranking): add station detail filter
fix(data): handle missing quality snapshot
chore(tooling): enable commit message linting
```

首次拉取仓库后执行一次 `npm install`，会自动安装 Git hooks；之后每次 `git commit` 都会校验提交信息格式。

## 任务说明

- `每日公告抓取`：默认启用，按计划抓取公开公告。
- `每日倍率快照更新`：默认启用，刷新公开倍率快照并重建前端数据。
- `排名与质量刷新`：功能已实现，但默认关闭，仅手动触发。
