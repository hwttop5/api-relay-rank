/**
 * 通用加载动画组件
 * 可在任何需要加载状态的地方使用
 */

interface LoadingSpinnerProps {
  size?: 'small' | 'medium' | 'large';
  text?: string;
  description?: string;
  showProgress?: boolean;
  className?: string;
}

export function LoadingSpinner({ 
  size = 'medium', 
  text = '加载中',
  description,
  showProgress = true,
  className = ''
}: LoadingSpinnerProps) {
  const sizeMap = {
    small: { spinner: 40, ring2: 30, dot: 8 },
    medium: { spinner: 60, ring2: 45, dot: 10 },
    large: { spinner: 80, ring2: 60, dot: 12 },
  };

  const sizes = sizeMap[size];

  return (
    <div className={`loading-spinner-container loading-spinner-${size} ${className}`}>
      {/* 旋转动画 */}
      <div 
        className="loading-spinner-rings" 
        style={{ 
          width: sizes.spinner, 
          height: sizes.spinner 
        }}
      >
        <div className="spinner-ring"></div>
        <div 
          className="spinner-ring spinner-ring-2"
          style={{
            width: sizes.ring2,
            height: sizes.ring2,
            top: (sizes.spinner - sizes.ring2) / 2,
            left: (sizes.spinner - sizes.ring2) / 2,
          }}
        ></div>
        <div 
          className="spinner-dot"
          style={{
            width: sizes.dot,
            height: sizes.dot,
            margin: `${-sizes.dot / 2}px 0 0 ${-sizes.dot / 2}px`,
          }}
        ></div>
      </div>

      {/* 文本 */}
      {text && (
        <div className="loading-spinner-text">
          <h3 className="loading-spinner-title">{text}</h3>
          {description && (
            <p className="loading-spinner-desc">{description}</p>
          )}
        </div>
      )}

      {/* 进度条 */}
      {showProgress && (
        <div className="loading-spinner-progress">
          <div className="loading-spinner-progress-bar"></div>
        </div>
      )}
    </div>
  );
}

/**
 * 简化版加载指示器（内联使用）
 */
export function LoadingIndicator({ size = 'small' }: { size?: 'small' | 'medium' | 'large' }) {
  const sizeMap = {
    small: 20,
    medium: 32,
    large: 48,
  };

  const spinnerSize = sizeMap[size];

  return (
    <div 
      className="loading-indicator" 
      style={{ width: spinnerSize, height: spinnerSize }}
      role="status"
      aria-label="加载中"
    >
      <div className="spinner-ring"></div>
    </div>
  );
}

/**
 * 全屏加载遮罩
 */
export function LoadingOverlay({ 
  text = '加载中', 
  description 
}: { 
  text?: string; 
  description?: string;
}) {
  return (
    <div className="loading-overlay" role="status" aria-live="polite">
      <div className="loading-overlay-content">
        <LoadingSpinner 
          size="large" 
          text={text} 
          description={description}
          showProgress={true}
        />
      </div>
    </div>
  );
}
