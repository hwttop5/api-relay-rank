/**
 * 增强型渐变卡片组件
 * 带有波浪装饰和悬浮效果
 */

interface GradientCardProps {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  icon?: React.ReactNode;
  highlight?: boolean;
  className?: string;
}

export function GradientCard({
  children,
  title,
  subtitle,
  icon,
  highlight = false,
  className = '',
}: GradientCardProps) {
  return (
    <div className={`card-enhanced ${highlight ? 'card-enhanced-highlight' : ''} ${className}`}>
      {(title || subtitle || icon) && (
        <div className="card-enhanced-header">
          {icon && (
            <div className="card-enhanced-icon icon-enhanced">
              {icon}
            </div>
          )}
          {title && (
            <h3 className="card-enhanced-title">{title}</h3>
          )}
          {subtitle && (
            <p className="card-enhanced-subtitle">{subtitle}</p>
          )}
        </div>
      )}
      <div className="card-enhanced-body">
        {children}
      </div>
    </div>
  );
}
