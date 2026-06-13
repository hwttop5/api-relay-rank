/**
 * 站点 PV 显示组件
 * 客户端动态加载 PV 数据，避免静态生成时数据为空的问题
 */
'use client';

import { useEffect, useState } from 'react';
import { formatCompactCount } from '@/lib/format';

interface StationPvDisplayProps {
  stationKey: string;
  fallbackValue?: number;
}

export function StationPvDisplay({ stationKey, fallbackValue = 0 }: StationPvDisplayProps) {
  const [pv, setPv] = useState<number | null>(fallbackValue);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function fetchPv() {
      try {
        const response = await fetch(`/api/page-view-stats?station=${encodeURIComponent(stationKey)}`);
        if (!response.ok) {
          throw new Error('Failed to fetch PV');
        }
        const data = await response.json();
        if (mounted && typeof data.pv === 'number') {
          setPv(data.pv);
        }
      } catch (error) {
        console.error('Failed to load station PV:', error);
        // 保持使用 fallback 值
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    fetchPv();

    return () => {
      mounted = false;
    };
  }, [stationKey]);

  if (isLoading && !fallbackValue) {
    return <span className="pv-loading">-</span>;
  }

  return <span>{formatCompactCount(pv ?? 0)}</span>;
}
