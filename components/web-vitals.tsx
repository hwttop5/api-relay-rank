/**
 * Web Vitals 性能监控组件
 * 收集核心性能指标并上报
 */
'use client';

import { useReportWebVitals } from 'next/web-vitals';

export function WebVitals() {
  useReportWebVitals((metric) => {
    // 开发环境打印到控制台
    if (process.env.NODE_ENV === 'development') {
      console.log(`[Web Vitals] ${metric.name}:`, Math.round(metric.value), metric.rating);
      return;
    }

    // 生产环境上报到百度统计（如果已配置）
    const hmt = (window as unknown as { _hmt?: unknown[][] })._hmt;
    if (Array.isArray(hmt)) {
      hmt.push([
        '_trackEvent',
        'web-vitals',
        metric.name,
        metric.rating,
        Math.round(metric.value),
      ]);
    }
  });

  return null;
}
