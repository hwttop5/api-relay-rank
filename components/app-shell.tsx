import Link from "next/link";
import type { ReactNode } from "react";

import { formatDateTime } from "@/lib/format";
import type { ShellData } from "@/lib/types";
import { ContactAdProvider, ContactAdTrigger } from "@/components/contact-ad";
import { MobileNavMenu } from "@/components/mobile-nav-menu";
import { NAV_ITEMS, type AppNavKey } from "@/components/nav-items";
import { SiteUptime } from "@/components/site-uptime";
import { ThemeControls, ThemeToggle } from "@/components/theme-toggle";

export function StatusChip({ label, tone = "default" }: { label: string; tone?: "default" | "accent" | "blue" | "warn" | "danger" | "success" }) {
  const cls =
    tone === "accent"
      ? "chip chip-accent"
      : tone === "blue"
        ? "chip chip-blue"
        : tone === "warn"
          ? "chip chip-warn"
          : tone === "danger"
            ? "chip chip-danger"
            : tone === "success"
              ? "chip chip-success"
              : "chip";
  return <span className={cls}>{label}</span>;
}

function BrandLogo() {
  return (
    <svg className="brand-logo" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <rect className="brand-logo__bg" x="4" y="4" width="56" height="56" rx="14" />
      <circle className="brand-logo__dish" cx="32" cy="35" r="20" />
      <circle className="brand-logo__ring brand-logo__ring-outer" cx="32" cy="35" r="20" />
      <circle className="brand-logo__ring brand-logo__ring-inner" cx="32" cy="35" r="12" />
      <path className="brand-logo__sweep-fill" d="M32 35L50 25A20 20 0 0 1 52 38Z" />
      <path className="brand-logo__sweep-line" d="M32 35L50 25" />
      <path className="brand-logo__ping" d="M18 35H24M32 15V21M44 35H50M32 47V53" />
      <circle className="brand-logo__core" cx="32" cy="35" r="4.6" />
      <path className="brand-logo__signal" d="M20 16H44" />
    </svg>
  );
}

export function AppShell({
  active,
  children,
  data,
  footerMeta,
  subtitle,
  title,
  actions,
  topbarMetaClassName
}: {
  active: AppNavKey;
  children: ReactNode;
  data: ShellData;
  footerMeta?: ReactNode;
  subtitle?: ReactNode;
  title?: ReactNode;
  actions?: ReactNode;
  topbarMetaClassName?: string;
}) {
  const topbarMetaClasses = ["topbar-meta", topbarMetaClassName].filter(Boolean).join(" ");
  const copyrightYear = new Date().getFullYear();

  return (
    <ContactAdProvider>
      <main className="app-shell">
        <div className="page-shell">
          <header className="topbar">
            <div className="topbar-main">
              <div className="topbar-brand-row">
                <div className="brand">
                  <div className="brand-title">
                    <BrandLogo />
                    <span>{title ?? data.siteName}</span>
                  </div>
                  <div className="brand-subtitle">{subtitle ?? `数据生成于 ${formatDateTime(data.generatedAt)}`}</div>
                </div>
                <div className="mobile-topbar-actions">
                  <ThemeToggle />
                  <ContactAdTrigger />
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
          <footer className="page-footer">
            {footerMeta ? (
              <span className="page-footer-line">
                <span>{footerMeta}</span>
                <span className="page-footer-separator">·</span>
                <SiteUptime />
                <span className="page-footer-separator">·</span>
                <span>Copyright © {copyrightYear} ttop5. All rights reserved.</span>
              </span>
            ) : (
              <span className="page-footer-line">
                <SiteUptime />
                <span className="page-footer-separator">·</span>
                <span>Copyright © {copyrightYear} ttop5. All rights reserved.</span>
              </span>
            )}
          </footer>
        </div>
      </main>
    </ContactAdProvider>
  );
}
