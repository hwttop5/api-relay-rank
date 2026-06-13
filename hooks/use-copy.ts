/**
 * 复制到剪贴板 Hook
 * 提供复制功能和状态管理
 */
'use client';

import { useState, useCallback } from 'react';

export function useCopy(duration = 2000) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), duration);
      return true;
    } catch (error) {
      console.error('Failed to copy:', error);
      return false;
    }
  }, [duration]);

  return { copied, copy };
}
