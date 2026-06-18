# 项目规则

## 协作准则

### 🌐 沟通语言
- 全程使用中文与用户交流

### 💻 开发流程

#### 1. 代码修改前
- 先阅读相关代码和文档
- 理解现有实现和项目结构
- 结合新需求规划改动方案

#### 2. 代码修改后
- 在本地启动服务进行测试
- 让用户验收功能
- 验收通过后再提交代码

#### 3. 样式规范
- 新页面/新功能的样式风格要与项目整体保持一致
- 注意字体大小、排版间距的统一性
- 遵循现有的设计系统

### ⚠️ 安全规则
- **数据库操作**：涉及线上数据库修改时，必须先让用户确认
- **敏感文件**：不提交包含 API tokens、密码等敏感信息的文件

### 📝 提交规范
- Commit 风格与 Release 说明要与项目历史保持一致
- 使用约定式提交格式（Conventional Commits）

### 🎨 风格一致性原则
**除非用户特别说明，否则所有内容都必须与项目现有风格保持一致：**
- **Commit消息风格**：格式、语言（英文/中文）、简洁度
- **文档风格**：结构、语气、Markdown格式
- **页面样式风格**：设计模式、组件风格、UI一致性
- **Release版本说明风格**：changelog格式、描述方式
- **代码风格**：命名规范、注释风格、文件组织方式

**执行方法：**
1. 开始工作前，先查看项目中的相关示例
2. 理解并遵循既定的风格规范
3. 保证新增内容与现有内容无缝衔接

---

## Git 提交规则

### ❌ 不应提交的文件类型

1. **临时任务文档** - 在执行具体任务时生成的分析、总结、清单等文档
   - 命名模式：`*_ANALYSIS.md`、`*_SUMMARY.md`、`*_CHECKLIST.md`、`*_COMPLETE.md`
   - 示例：`PERFORMANCE_ANALYSIS.md`、`DEPLOYMENT_CHECKLIST.md`、`OPTIMIZATION_SUMMARY.md`
   - 这些文档只保留在本地供开发参考，不提交到仓库

2. **临时任务目录** - 包含多个临时文档的目录
   - `docs/optimization/` - 优化任务文档
   - `docs/tasks/` - 任务记录
   - `docs/temp/` - 临时文档

3. **敏感文件**
   - `*auth-capture.json` - 包含 API tokens 的认证文件
   - `.env`、`.env.local` - 环境变量配置

4. **生成的输出文件**
   - `*.csv` 审计输出（`composite_ranking_*.csv`、`multiplier_*.csv` 等）
   - `*.log` 日志文件
   - `*.bak` 备份文件
   - `tsconfig.tsbuildinfo` 构建缓存

5. **临时脚本**
   - `screenshot.js` 等调试脚本

### ✅ 应该提交的文档

1. **项目核心文档**
   - `README.md` - 项目说明
   - `CHANGELOG.md` - 变更日志
   - `AGENTS.md` - 项目文档

2. **正式维护文档**（`docs/` 目录下）
   - `data-refresh-notes.md` - 数据刷新维护手册
   - `docker-deploy.md` - Docker 部署文档
   - `frontend-display-notes.md` - 前端展示规则

### 执行原则

- 临时任务文档生成后，**只保留在本地**，不执行 `git add`
- 如果不小心提交了，应立即用 `git rm --cached` 移除跟踪
- `.gitignore` 已配置相关规则，但仍需人工注意
