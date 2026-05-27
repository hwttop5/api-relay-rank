"use client";

import { Github, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { ContactAdTrigger } from "@/components/contact-ad";

type ThemeMode = "dark" | "light";

const STORAGE_KEY = "api-relay-rank-theme";
const REPO_URL = "https://github.com/hwttop5/api-relay-rank";

function getInitialTheme(): ThemeMode {
  if (typeof window === "undefined") {
    return "dark";
  }

  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "dark" || stored === "light") {
    return stored;
  }

  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme: ThemeMode) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeMode>("dark");

  useEffect(() => {
    const initialTheme = getInitialTheme();
    setTheme(initialTheme);
    applyTheme(initialTheme);
  }, []);

  const nextTheme = theme === "dark" ? "light" : "dark";
  const label = theme === "dark" ? "切换到白色主题" : "切换到黑色主题";

  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={label}
      title={label}
      onClick={() => {
        setTheme(nextTheme);
        window.localStorage.setItem(STORAGE_KEY, nextTheme);
        applyTheme(nextTheme);
      }}
    >
      {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}

export function ThemeControls() {
  return (
    <div className="topbar-icon-group">
      <ThemeToggle />
      <ContactAdTrigger />
      <a
        href={REPO_URL}
        target="_blank"
        rel="noreferrer"
        className="icon-button icon-button-github"
        aria-label="项目地址"
        title="项目地址"
      >
        <Github size={15} />
      </a>
    </div>
  );
}
