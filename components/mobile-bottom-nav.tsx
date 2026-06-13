/**
 * 移动端底部导航栏
 * 提供快速访问主要页面的导航
 */
'use client';

import { usePathname } from 'next/navigation';
import Link from 'next/link';
import type { Route } from 'next';
import { Home, FileText, BarChart3, Info } from 'lucide-react';

export function MobileBottomNav() {
  const pathname = usePathname();

  const navItems = [
    { 
      href: '/ranking', 
      label: '排名', 
      icon: Home,
      description: '查看排名'
    },
    { 
      href: '/submit', 
      label: '提交', 
      icon: FileText,
      description: '提交站点'
    },
    { 
      href: '/audit', 
      label: '审计', 
      icon: BarChart3,
      description: '站点审计'
    },
    { 
      href: '/statement', 
      label: '声明', 
      icon: Info,
      description: '项目声明'
    },
  ] satisfies Array<{
    href: Route;
    label: string;
    icon: typeof Home;
    description: string;
  }>;

  // 触觉反馈（如果支持）
  const handleVibrate = () => {
    if ('vibrate' in navigator) {
      navigator.vibrate(10);
    }
  };

  return (
    <nav className="mobile-bottom-nav" role="navigation" aria-label="主导航">
      {navItems.map(({ href, label, icon: Icon, description }) => {
        const isActive = pathname === href || 
                        (href === '/ranking' && pathname === '/');
        return (
          <Link
            key={href}
            href={href}
            className={`mobile-bottom-nav-item ${isActive ? 'is-active' : ''}`}
            aria-label={description}
            aria-current={isActive ? 'page' : undefined}
            onClick={handleVibrate}
          >
            <Icon size={20} aria-hidden="true" />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
