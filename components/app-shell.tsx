import Link from "next/link";
import { Radar } from "lucide-react";
import type { ReactNode } from "react";

import { formatDateTime } from "@/lib/format";
import type { SiteData } from "@/lib/types";
import { MobileNavMenu } from "@/components/mobile-nav-menu";
import { NAV_ITEMS, type AppNavKey } from "@/components/nav-items";
import { ThemeControls, ThemeToggle } from "@/components/theme-toggle";

export function StatusChip({ label, tone = "default" }: { label: string; tone?: "default" | "accent" | "blue" | "warn" | "danger" }) {
  const cls =
    tone === "accent"
      ? "chip chip-accent"
      : tone === "blue"
        ? "chip chip-blue"
        : tone === "warn"
          ? "chip chip-warn"
          : tone === "danger"
            ? "chip chip-danger"
            : "chip";
  return <span className={cls}>{label}</span>;
}

export function AppShell({
  active,
  children,
  data,
  subtitle,
  title,
  actions,
  topbarMetaClassName
}: {
  active: AppNavKey;
  children: ReactNode;
  data: SiteData;
  subtitle?: ReactNode;
  title?: ReactNode;
  actions?: ReactNode;
  topbarMetaClassName?: string;
}) {
  const topbarMetaClasses = ["topbar-meta", topbarMetaClassName].filter(Boolean).join(" ");

  return (
    <main className="app-shell">
      <div className="page-shell">
        <header className="topbar">
          <div className="topbar-main">
            <div className="topbar-brand-row">
              <div className="brand">
                <div className="brand-title">
                  <Radar size={18} aria-hidden="true" />
                  <span>{title ?? data.siteName}</span>
                </div>
                <div className="brand-subtitle">{subtitle ?? `数据生成于 ${formatDateTime(data.generatedAt)}`}</div>
              </div>
              <div className="mobile-topbar-actions">
                <ThemeToggle />
                <MobileNavMenu active={active} />
              </div>
            </div>
            <nav className="main-nav" aria-label="主导航">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <Link key={item.key} href={item.href} className={active === item.key ? "nav-link is-active" : "nav-link"}>
                    <Icon size={15} aria-hidden="true" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className={topbarMetaClasses}>
            {actions}
            <div className="desktop-theme-controls">
              <ThemeControls />
            </div>
          </div>
        </header>
        {children}
      </div>
    </main>
  );
}
