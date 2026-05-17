"use client";

import Link from "next/link";
import { Github, Menu, X } from "lucide-react";
import { useState } from "react";

import { NAV_ITEMS, type AppNavKey } from "@/components/nav-items";

const REPO_URL = "https://github.com/hwttop5/api-relay-rank";

export function MobileNavMenu({ active }: { active: AppNavKey }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="mobile-nav">
      <button
        type="button"
        className="mobile-nav-trigger"
        aria-label={isOpen ? "关闭导航菜单" : "打开导航菜单"}
        aria-expanded={isOpen}
        aria-controls="mobile-nav-panel"
        onClick={() => setIsOpen((current) => !current)}
      >
        {isOpen ? <X size={18} /> : <Menu size={18} />}
      </button>

      {isOpen ? (
        <div id="mobile-nav-panel" className="mobile-nav-panel">
          <nav className="mobile-nav-links" aria-label="移动端主导航">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.key}
                  href={item.href}
                  className={active === item.key ? "mobile-nav-link is-active" : "mobile-nav-link"}
                  onClick={() => setIsOpen(false)}
                >
                  <Icon size={16} aria-hidden="true" />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          <div className="mobile-nav-tools">
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="mobile-nav-tool">
              <Github size={16} aria-hidden="true" />
              <span>GitHub 仓库</span>
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
