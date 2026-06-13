/**
 * 增强型弹窗组件
 * 基于 404 页面风格设计
 */
'use client';

import { useEffect } from 'react';
import { X } from 'lucide-react';

interface EnhancedModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'small' | 'medium' | 'large';
}

export function EnhancedModal({
  isOpen,
  onClose,
  title,
  subtitle,
  icon,
  children,
  footer,
  size = 'medium',
}: EnhancedModalProps) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="modal-enhanced-overlay" onClick={onClose}>
      <div 
        className={`modal-enhanced-dialog modal-enhanced-${size}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 关闭按钮 */}
        <button 
          className="modal-enhanced-close"
          onClick={onClose}
          aria-label="关闭"
        >
          <X size={24} />
        </button>

        {/* 头部 */}
        <div className="modal-enhanced-header">
          {icon && (
            <div className="modal-enhanced-icon icon-enhanced">
              {icon}
            </div>
          )}
          <h2 className="modal-enhanced-title">{title}</h2>
          {subtitle && (
            <p className="modal-enhanced-subtitle">{subtitle}</p>
          )}
          <div className="wave-decoration" aria-hidden="true" />
        </div>

        {/* 内容 */}
        <div className="modal-enhanced-body">
          {children}
        </div>

        {/* 底部 */}
        {footer && (
          <div className="modal-enhanced-footer">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
