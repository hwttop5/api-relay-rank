/**
 * 增强型页面标题组件
 * 基于 404 页面风格设计
 */

interface HeroTitleProps {
  children: React.ReactNode;
  subtitle?: string;
  icon?: React.ReactNode;
  className?: string;
}

export function HeroTitle({ children, subtitle, icon, className = '' }: HeroTitleProps) {
  return (
    <div className={`hero-title-container ${className}`}>
      {icon && (
        <div className="hero-title-icon icon-enhanced">
          {icon}
        </div>
      )}
      <h1 className="section-title-enhanced">
        {children}
      </h1>
      {subtitle && (
        <p className="hero-title-subtitle">{subtitle}</p>
      )}
      <div className="wave-decoration" aria-hidden="true" />
    </div>
  );
}
