# Claude Code 工作流程规范

## 代码修改流程（重要）

### ⚠️ 提交前验收规则

**任何代码修改后，必须按以下顺序进行：**

1. **本地构建验证**
   ```bash
   npm run build
   ```
   确保构建成功，无 TypeScript 错误

2. **启动本地服务**
   ```bash
   npm run start
   ```
   在生产模式下启动服务供用户验收

3. **等待用户验收**
   - ❌ **禁止**直接 git commit 和 git push
   - ✅ 让用户在本地测试功能是否正常
   - ✅ 用户确认通过后再提交代码

4. **验收通过后提交**
   ```bash
   git add -A
   git commit -m "..."
   git push
   ```

### 例外情况

以下情况可以直接提交：
- 纯文档修改（README、.md 文件）
- 配置文件优化（不影响功能）
- 明确的 bug 修复（用户已确认问题）

### 流程示例

```bash
# ❌ 错误流程
修改代码 → npm run build → git commit → git push

# ✅ 正确流程  
修改代码 → npm run build → npm run start → 等待用户验收 → git commit → git push
```

---

**记住：代码修改 → 本地验收 → 用户确认 → 提交推送**
