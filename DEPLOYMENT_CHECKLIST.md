# 性能优化部署检查清单

## 部署前准备 ✅

- [x] 所有代码已提交到 Git
- [x] 本地构建成功验证
- [x] TypeScript 类型检查通过
- [x] 所有依赖已安装并锁定版本

## 部署监控

### 1. 自动部署状态
检查 Vercel/部署平台是否已自动触发构建：
- [ ] 构建任务已启动
- [ ] 构建日志无错误
- [ ] 部署成功完成

### 2. 功能验证
访问生产环境验证核心功能：
- [ ] 首页 `/ranking` 正常加载
- [ ] 排名列表正确显示
- [ ] 站点详情页 `/stations/[station]` 可访问
- [ ] PV 数据正常显示（需刷新后加载）
- [ ] 用户评价功能正常
- [ ] API 接口正常响应

### 3. 性能指标监控（生产环境）
打开浏览器 DevTools Console 查看 Web Vitals 输出：

| 指标 | 目标值 | 实际值 | 状态 |
|------|--------|--------|------|
| FCP (First Contentful Paint) | < 1.0s | ___ | [ ] |
| LCP (Largest Contentful Paint) | < 2.0s | ___ | [ ] |
| FID (First Input Delay) | < 100ms | ___ | [ ] |
| CLS (Cumulative Layout Shift) | < 0.1 | ___ | [ ] |
| TTFB (Time to First Byte) | < 500ms | ___ | [ ] |

### 4. 缓存验证
检查 Network 面板验证缓存策略：

**静态资源**：
- [ ] `/_next/static/*` 返回 `Cache-Control: public, max-age=31536000, immutable`
- [ ] 图片资源返回 `Cache-Control: public, max-age=2592000`

**API 响应**：
- [ ] `/api/page-view-stats` 返回 `Cache-Control: public, max-age=300`
- [ ] 响应头包含 `Content-Encoding: br` 或 `gzip`

### 5. Bundle 体积检查
构建日志中的关键指标：
- [ ] First Load JS < 110 kB
- [ ] 页面 JS 体积合理（< 10 kB per page）
- [ ] Shared chunks 正常分离

## 性能基线对比

### 部署前（估算）
- 首次加载时间: ~2.5s
- LCP: ~2.2s
- 数据库查询: ~200ms
- API 响应: ~150ms

### 部署后（实测）
- 首次加载时间: ___s  (目标: < 1.3s)
- LCP: ___s  (目标: < 1.1s)
- 数据库查询: ___ms  (目标: < 50ms)
- API 响应: ___ms  (目标: < 45ms)

## 回滚计划

如果出现问题，可立即回滚：
```bash
# 回滚到上一个提交
git revert f6be73f
git push origin master

# 或回滚到指定版本
git reset --hard df06d3b
git push origin master --force
```

## 后续优化建议

### 立即可选
1. **启用 Redis**：配置 `REDIS_URL` 环境变量启用分布式缓存
2. **Bundle 分析**：运行 `ANALYZE=true npm run build` 查看依赖详情

### 中期优化
1. **图片优化**：将 QR 码图片转换为 next/image
2. **Critical CSS**：内联关键 CSS 到 layout
3. **CDN 配置**：使用专用 CDN 加速静态资源

### 监控增强
1. **Sentry 集成**：监控运行时错误
2. **性能仪表板**：汇总 Web Vitals 数据到 Baidu Tongji
3. **缓存命中率**：添加日志统计缓存效果

## 问题排查

### 缓存未生效
- 检查 `.env` 是否正确部署
- 验证 `next.config.mjs` 是否被正确加载
- 清除浏览器缓存重新测试

### 性能未达预期
- 检查数据库连接池配置是否生效
- 验证内存缓存是否正常工作（查看控制台日志）
- 使用 Chrome DevTools Performance 分析瓶颈

### 构建失败
- 检查 TypeScript 编译错误
- 验证所有依赖是否正确安装
- 查看构建日志详细错误信息

---

**部署时间**: ___
**验证人**: ___
**最终状态**: [ ] 成功 / [ ] 需调整 / [ ] 已回滚
