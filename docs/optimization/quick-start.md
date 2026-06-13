# 🚀 快速开始指南

## 如何使用新增的优化功能

---

## 📦 新增的组件和 Hooks

### 可用组件
\\\	ypescript
import {
  Tooltip,           // 提示组件
  LazyImage,         // 懒加载图片
  MobileBottomNav,   // 移动端底部导航
  TableSkeleton,     // 表格骨架屏
  CardSkeleton,      // 卡片骨架屏
  CardListSkeleton,  // 卡片列表骨架屏
  DetailCardSkeleton,// 详情卡片骨架屏
  SectionSkeleton,   // 区块骨架屏
} from '@/components';

import { useCopy } from '@/hooks';  // 复制功能 Hook
\\\

---

## 🎯 集成步骤

### 步骤 1: 添加底部导航栏（移动端）

在 **app/layout.tsx** 中添加：

\\\	sx
import { MobileBottomNav } from '@/components/mobile-bottom-nav';

export default function RootLayout({ children }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        {/* 其他内容 */}
        {children}
        
        {/* 添加移动端底部导航 */}
        <MobileBottomNav />
      </body>
    </html>
  );
}
\\\

---

### 步骤 2: 在数据加载时显示骨架屏

例如在 **components/ranking-dashboard.tsx**：

\\\	sx
import { TableSkeleton, CardListSkeleton } from '@/components/skeleton';

export function RankingDashboard({ data }) {
  const [isLoading, setIsLoading] = useState(true);
  
  if (isLoading) {
    return (
      <>
        {/* 桌面端：表格骨架屏 */}
        <div className="desktop-table">
          <table className="data-table">
            <TableSkeleton rows={10} />
          </table>
        </div>
        
        {/* 移动端：卡片骨架屏 */}
        <CardListSkeleton cards={5} />
      </>
    );
  }
  
  return (
    // 实际数据渲染
  );
}
\\\

---

### 步骤 3: 为图标按钮添加 Tooltip

例如在 **components/topbar.tsx**：

\\\	sx
import { Tooltip } from '@/components/tooltip';

<div className="topbar-icon-group">
  <Tooltip content="切换深色/浅色主题" position="bottom">
    <button className="theme-toggle" onClick={toggleTheme}>
      <Sun size={18} />
    </button>
  </Tooltip>
  
  <Tooltip content="联系方式" position="bottom">
    <button className="icon-button contact-ad-trigger">
      <Mail size={18} />
    </button>
  </Tooltip>
</div>
\\\

---

### 步骤 4: 使用复制功能

例如在站点详情页：

\\\	sx
'use client';

import { useCopy } from '@/hooks/use-copy';
import { Copy, Check } from 'lucide-react';

function CopyUrlButton({ url }: { url: string }) {
  const { copied, copy } = useCopy();
  
  return (
    <button 
      className={\	iny-button copy-button \\}
      onClick={() => copy(url)}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? '已复制' : '复制链接'}
      {copied && <span className="copy-feedback">✓ 已复制到剪贴板</span>}
    </button>
  );
}
\\\

---

### 步骤 5: 使用懒加载图片

替换现有的 \<img>\ 标签：

\\\	sx
import { LazyImage } from '@/components/lazy-image';

// 之前
<img src={avatarUrl} alt="用户头像" className="feedback-avatar" />

// 之后
<LazyImage 
  src={avatarUrl} 
  alt="用户头像" 
  className="feedback-avatar"
  width={34}
  height={34}
/>
\\\

---

### 步骤 6: 表单验证动画

在表单组件中使用：

\\\	sx
import { AlertCircle, CheckCircle } from 'lucide-react';

function FormField({ error, success }) {
  return (
    <div className="feedback-field">
      <input
        type="text"
        className={error ? 'input-error' : success ? 'input-success' : ''}
      />
      
      {error && (
        <div className="error-message">
          <AlertCircle size={14} />
          {error}
        </div>
      )}
      
      {success && (
        <div className="success-message">
          <CheckCircle size={14} />
          验证成功
        </div>
      )}
    </div>
  );
}
\\\

---

## 🎨 自动启用的样式优化

以下优化已自动生效，无需额外代码：

### ✅ 已启用
- 按钮 hover 上移效果
- 链接下划线展开动画
- 卡片悬浮效果
- 表格行高亮
- 排名奖牌脉动动画
- 慈善徽章闪烁效果
- 主题切换平滑过渡
- 焦点可见性增强

---

## 📱 移动端优化

### 底部导航栏
- **自动显示**: 仅在屏幕宽度 ≤ 640px 时显示
- **触觉反馈**: 支持震动反馈（如果设备支持）
- **当前页高亮**: 自动根据路由高亮
- **Safe Area**: 自动适配 iOS 刘海屏

### 响应式动画
- **自动适配**: prefers-reduced-motion 用户偏好
- **性能优化**: GPU 加速，避免卡顿
- **流畅体验**: 60fps 动画帧率

---

## 🧪 测试清单

### 功能测试
- [ ] 骨架屏在加载时正常显示
- [ ] Tooltip 在 hover 时出现
- [ ] 复制按钮显示"已复制"提示
- [ ] 表单错误时有抖动动画
- [ ] 主题切换平滑无闪烁
- [ ] 奖牌有脉动效果
- [ ] 移动端底部导航正常工作

### 兼容性测试
- [ ] Chrome/Edge - 正常
- [ ] Firefox - 正常
- [ ] Safari - 正常
- [ ] iOS Safari - 正常
- [ ] Android Chrome - 正常

### 性能测试
- [ ] Lighthouse 性能分 > 85
- [ ] 动画流畅不卡顿
- [ ] 懒加载节省流量

---

## 🐛 常见问题

### Q: 底部导航没有显示？
A: 确保在移动端视图（宽度 ≤ 640px）下查看，或检查是否正确导入组件。

### Q: Tooltip 不显示？
A: 检查是否提供了 \content\ 属性，并且组件是客户端组件（'use client'）。

### Q: 复制功能不工作？
A: 确保在 HTTPS 环境下，或 localhost 开发环境。

### Q: 骨架屏样式不对？
A: 检查 CSS 是否正确加载，确保 globals.css 被引入。

### Q: 动画太慢/太快？
A: 可以在 CSS 中调整 transition 和 animation 的 duration 值。

---

## 📚 更多资源

- **完整文档**: implementation-complete.md
- **组件示例**: 查看各组件的 TSX 文件注释
- **样式参考**: app/globals.css 末尾的新增样式

---

## 🎯 下一步建议

1. **立即集成**: 按照上述步骤集成新组件
2. **测试验证**: 在各设备和浏览器测试
3. **性能监控**: 使用 Lighthouse 检查性能
4. **用户反馈**: 收集实际用户的使用反馈
5. **持续优化**: 根据反馈进行迭代优化

---

**需要帮助？** 查看各组件文件中的详细注释和使用示例。
