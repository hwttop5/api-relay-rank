/**
 * 增强型按钮组件
 * 基于 404 页面按钮风格
 */

import React from 'react';

interface EnhancedButtonProps {
  children: React.ReactNode;
  variant?: 'primary' | 'secondary';
  size?: 'default' | 'large' | 'small';
  icon?: React.ReactNode;
  iconPosition?: 'left' | 'right';
  onClick?: () => void;
  disabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
  className?: string;
}

export function EnhancedButton({
  children,
  variant = 'primary',
  size = 'default',
  icon,
  iconPosition = 'left',
  onClick,
  disabled = false,
  type = 'button',
  className = '',
}: EnhancedButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`button-enhanced button-enhanced-${variant} button-enhanced-${size} ${className}`}
    >
      {icon && iconPosition === 'left' && (
        <span className="button-enhanced-icon">{icon}</span>
      )}
      <span className="button-enhanced-text">{children}</span>
      {icon && iconPosition === 'right' && (
        <span className="button-enhanced-icon">{icon}</span>
      )}
    </button>
  );
}
