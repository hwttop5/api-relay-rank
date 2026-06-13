/**
 * 404 页面插图组件
 * 可选的视觉装饰元素
 */

export function NotFoundIllustration() {
  return (
    <svg
      className="not-found-illustration"
      viewBox="0 0 400 300"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* 背景圆圈 */}
      <circle cx="200" cy="150" r="120" fill="var(--accent-soft)" opacity="0.3">
        <animate
          attributeName="r"
          values="120;130;120"
          dur="3s"
          repeatCount="indefinite"
        />
      </circle>
      
      {/* 搜索图标 */}
      <g className="search-icon">
        <circle
          cx="160"
          cy="120"
          r="40"
          stroke="var(--accent)"
          strokeWidth="6"
          fill="none"
        />
        <line
          x1="190"
          y1="150"
          x2="220"
          y2="180"
          stroke="var(--accent)"
          strokeWidth="6"
          strokeLinecap="round"
        />
      </g>
      
      {/* 问号 */}
      <g className="question-mark" opacity="0.6">
        <circle cx="240" cy="100" r="8" fill="var(--accent-2)" />
        <path
          d="M 240 70 Q 240 50, 260 50 T 260 70 Q 260 85, 240 90"
          stroke="var(--accent-2)"
          strokeWidth="4"
          fill="none"
          strokeLinecap="round"
        />
      </g>
      
      {/* 装饰点 */}
      <circle cx="100" cy="80" r="4" fill="var(--accent)">
        <animate
          attributeName="opacity"
          values="0.3;1;0.3"
          dur="2s"
          repeatCount="indefinite"
        />
      </circle>
      <circle cx="300" cy="120" r="4" fill="var(--accent-2)">
        <animate
          attributeName="opacity"
          values="1;0.3;1"
          dur="2s"
          repeatCount="indefinite"
        />
      </circle>
      <circle cx="120" cy="220" r="4" fill="var(--accent)">
        <animate
          attributeName="opacity"
          values="0.5;1;0.5"
          dur="2.5s"
          repeatCount="indefinite"
        />
      </circle>
    </svg>
  );
}
