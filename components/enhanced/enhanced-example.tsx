/**
 * 增强风格使用示例
 * 展示如何使用新的增强组件
 */

import { HeroTitle, MetricCard, EnhancedButton, GradientCard, EnhancedModal } from './index';
import { Sparkles, Users, TrendingUp, CheckCircle, Send, Star, AlertCircle } from 'lucide-react';
import { useState } from 'react';

export function EnhancedExamplePage() {
  const [isModalOpen, setIsModalOpen] = useState(false);

  return (
    <div className="page-shell">
      {/* 超大标题 */}
      <HeroTitle 
        icon={<Sparkles size={48} />}
        subtitle="基于 404 页面风格的全新设计系统"
      >
        增强风格示例
      </HeroTitle>

      {/* 指标卡片网格 */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', 
        gap: 24,
        marginBottom: 48 
      }}>
        <MetricCard
          value="156"
          label="注册站点"
          subtitle="较上月 +12"
          icon={<Users size={32} />}
          trend="up"
        />
        <MetricCard
          value="98.5%"
          label="服务可用率"
          subtitle="稳定运行"
          icon={<CheckCircle size={32} />}
        />
        <MetricCard
          value="1.2k"
          label="活跃用户"
          subtitle="较上月 +156"
          icon={<TrendingUp size={32} />}
          trend="up"
        />
      </div>

      {/* 渐变卡片 */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', 
        gap: 24,
        marginBottom: 48 
      }}>
        <GradientCard
          title="优质站点"
          subtitle="质量评分 > 90"
          icon={<Star size={32} />}
          highlight
        >
          <p>这些站点提供卓越的服务质量，响应速度快，稳定性高。</p>
        </GradientCard>

        <GradientCard
          title="新增站点"
          subtitle="本月新注册"
          icon={<Sparkles size={32} />}
        >
          <p>欢迎新加入的站点，我们会持续监控服务质量。</p>
        </GradientCard>
      </div>

      {/* 按钮组 */}
      <div style={{ 
        display: 'flex', 
        gap: 16, 
        justifyContent: 'center',
        flexWrap: 'wrap',
        marginBottom: 48 
      }}>
        <EnhancedButton 
          variant="primary" 
          size="large"
          icon={<Send size={20} />}
          onClick={() => setIsModalOpen(true)}
        >
          打开弹窗示例
        </EnhancedButton>

        <EnhancedButton 
          variant="secondary" 
          size="large"
          icon={<Star size={20} />}
        >
          查看更多
        </EnhancedButton>
      </div>

      {/* 分隔线 */}
      <hr className="divider-enhanced" />

      {/* CSS 类示例 */}
      <div style={{ textAlign: 'center', marginBottom: 48 }}>
        <h2 className="section-title-enhanced">CSS 类示例</h2>
        <p style={{ fontSize: 18, color: 'var(--muted-strong)', marginBottom: 32 }}>
          也可以直接使用 CSS 类来实现相同效果
        </p>

        <div className="metric-number-mega" style={{ marginBottom: 16 }}>
          999+
        </div>

        <span className="badge-enhanced">
          <Sparkles size={16} />
          热门标签
        </span>
      </div>

      {/* 增强弹窗示例 */}
      <EnhancedModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="提交成功"
        subtitle="您的站点已成功提交审核"
        icon={<CheckCircle size={64} />}
        size="medium"
        footer={
          <>
            <EnhancedButton 
              variant="secondary" 
              onClick={() => setIsModalOpen(false)}
            >
              返回
            </EnhancedButton>
            <EnhancedButton 
              variant="primary" 
              onClick={() => setIsModalOpen(false)}
            >
              知道了
            </EnhancedButton>
          </>
        }
      >
        <div style={{ textAlign: 'center', padding: 20 }}>
          <p style={{ fontSize: 16, lineHeight: 1.7, marginBottom: 16 }}>
            感谢您提交站点信息！我们会在 1-2 个工作日内完成审核。
          </p>
          <p style={{ fontSize: 14, color: 'var(--muted)' }}>
            审核通过后，您将收到邮件通知。
          </p>
        </div>
      </EnhancedModal>
    </div>
  );
}
