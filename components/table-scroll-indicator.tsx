/**
 * 表格滚动指示器
 * 当表格可以横向滚动时显示视觉提示
 */
'use client';

import { useEffect, useRef } from 'react';

export function TableScrollIndicator({ children }: { children: React.ReactNode }) {
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;

    const checkOverflow = () => {
      const hasOverflow = wrapper.scrollWidth > wrapper.clientWidth;
      if (hasOverflow) {
        wrapper.classList.add('has-overflow');
      } else {
        wrapper.classList.remove('has-overflow');
      }
    };

    // 初始检查
    checkOverflow();

    // 监听窗口大小变化
    const resizeObserver = new ResizeObserver(checkOverflow);
    resizeObserver.observe(wrapper);

    return () => {
      resizeObserver.disconnect();
    };
  }, []);

  return (
    <div ref={wrapperRef} className="table-wrap">
      {children}
    </div>
  );
}
