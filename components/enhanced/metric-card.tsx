/**
 * 增强型指标卡片组件
 * 显示超大数字和统计信息
 */

interface MetricCardProps {
  value: string | number;
  label: string;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: 'up' | 'down' | 'neutral';
  className?: string;
}

export function MetricCard({ 
  value, 
  label, 
  subtitle, 
  icon, 
  trend,
  className = '' 
}: MetricCardProps) {
  return (
    <div className={`card-enhanced metric-card ${className}`}>
      {icon && (
        <div className="metric-card-icon">
          {icon}
        </div>
      )}
      <div className="metric-number-mega">
        {value}
      </div>
      <div className="metric-card-label">
        {label}
      </div>
      {subtitle && (
        <div className="metric-card-subtitle">
          {subtitle}
        </div>
      )}
      {trend && (
        <div className={`metric-card-trend metric-card-trend-${trend}`}>
          {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'}
        </div>
      )}
    </div>
  );
}
