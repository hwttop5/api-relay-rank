"use client";

import dynamic from "next/dynamic";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Clock, Megaphone, ShieldCheck, X } from "lucide-react";

const CONFIG_URL = "/api/contact-ad";
const STORAGE_KEY = "api-relay-rank-contact-ad-dismissal";
const AnnouncementContent = dynamic(
  () => import("@/components/announcement-markdown").then((mod) => mod.AnnouncementContent),
  { ssr: false },
);

type ContactAdDismissal =
  | {
      type: "today";
      date: string;
    }
  | {
      type: "permanent";
    };

type ContactAdContextValue = {
  openAd: () => void;
};

const ContactAdContext = createContext<ContactAdContextValue | null>(null);

type ContactAdConfig = {
  title: string;
  updatedAt: string;
  content: string;
  contentHtml: string;
  sourceUrl: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeConfig(value: unknown): ContactAdConfig | null {
  if (!isRecord(value)) {
    return null;
  }

  const title = getString(value.title);
  const updatedAt = getString(value.updatedAt);
  const content = getString(value.content);
  const contentHtml = getString(value.contentHtml);
  const sourceUrl = getString(value.sourceUrl);

  if (!title || (!content && !contentHtml)) {
    return null;
  }

  return {
    title,
    updatedAt,
    content,
    contentHtml,
    sourceUrl,
  };
}

function getTodayKey() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function readDismissal(): ContactAdDismissal | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const value = parsed as Partial<ContactAdDismissal>;
    if (value.type === "permanent") {
      return { type: "permanent" };
    }
    if (value.type === "today" && "date" in value && typeof value.date === "string") {
      return { type: "today", date: value.date };
    }
  } catch {
    return null;
  }

  return null;
}

function shouldAutoOpen() {
  if (typeof window === "undefined") {
    return false;
  }

  const dismissal = readDismissal();
  if (!dismissal) {
    return true;
  }
  if (dismissal.type === "permanent") {
    return false;
  }

  return dismissal.date !== getTodayKey();
}

function useContactAd() {
  const context = useContext(ContactAdContext);
  if (!context) {
    throw new Error("ContactAd components must be rendered inside ContactAdProvider.");
  }
  return context;
}

export function ContactAdProvider({ children, autoOpen = false }: { children: ReactNode; autoOpen?: boolean }) {
  const [config, setConfig] = useState<ContactAdConfig | null>(null);
  const [dialogMode, setDialogMode] = useState<"announcement" | "empty" | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const loadConfig = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch(CONFIG_URL, {
        cache: "no-store",
        signal,
      });
      if (!response.ok) {
        setConfig(null);
        return null;
      }

      const nextConfig = normalizeConfig(await response.json());
      setConfig(nextConfig);
      return nextConfig;
    } catch {
      if (!signal?.aborted) {
        setConfig(null);
      }
      return null;
    }
  }, []);

  useEffect(() => {
    if (!autoOpen) {
      return;
    }

    const controller = new AbortController();

    async function bootstrap() {
      const nextConfig = await loadConfig(controller.signal);
      if (nextConfig && shouldAutoOpen()) {
        setDialogMode("announcement");
      }
    }

    void bootstrap();

    return () => controller.abort();
  }, [autoOpen, loadConfig]);

  useEffect(() => {
    if (!dialogMode) {
      return;
    }

    closeButtonRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDialogMode(null);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dialogMode]);

  const openAd = useCallback(() => {
    async function showDialog() {
      if (config) {
        setDialogMode("announcement");
        return;
      }

      const nextConfig = await loadConfig();
      if (nextConfig) {
        setDialogMode("announcement");
        return;
      }

      setDialogMode("empty");
    }

    void showDialog();
  }, [config, loadConfig]);

  const closeAd = useCallback(() => setDialogMode(null), []);

  const dismissToday = useCallback(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ type: "today", date: getTodayKey() } satisfies ContactAdDismissal));
    setDialogMode(null);
  }, []);

  const dismissPermanently = useCallback(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ type: "permanent" } satisfies ContactAdDismissal));
    setDialogMode(null);
  }, []);

  const contextValue = useMemo(() => ({ openAd }), [openAd]);
  const announcementConfig = dialogMode === "announcement" ? config : null;
  const isAnnouncementDialog = Boolean(announcementConfig);

  return (
    <ContactAdContext.Provider value={contextValue}>
      {children}
      {dialogMode ? (
        <div
          className="contact-ad-overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeAd();
            }
          }}
        >
          <section
            className="contact-ad-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="contact-ad-title"
            aria-describedby={isAnnouncementDialog ? undefined : "contact-ad-empty-text"}
          >
            <button ref={closeButtonRef} type="button" className="icon-button contact-ad-close" aria-label="关闭消息通知弹窗" title="关闭" onClick={closeAd}>
              <X size={16} />
            </button>

            <div className="contact-ad-dialog-head">
              <div className="contact-ad-dialog-icon">
                <Megaphone size={16} aria-hidden="true" />
              </div>
              <div>
                <h2 id="contact-ad-title">{announcementConfig ? announcementConfig.title : "消息通知"}</h2>
              </div>
            </div>

            {announcementConfig ? (
              <>
                <div className="contact-ad-body">
                  <AnnouncementContent content={announcementConfig.content} contentHtml={announcementConfig.contentHtml} className="contact-ad-markdown" />
                </div>
              </>
            ) : (
              <div className="contact-ad-body">
                <div id="contact-ad-empty-text" className="contact-ad-empty">
                  暂无公告
                </div>
              </div>
            )}

            <div className="contact-ad-actions">
              {announcementConfig ? (
                <>
                  <button type="button" className="tiny-button contact-ad-action contact-ad-action-today" onClick={dismissToday}>
                    <Clock size={13} aria-hidden="true" />
                    今日已读
                  </button>
                  <button type="button" className="tiny-button contact-ad-action" onClick={dismissPermanently}>
                    <ShieldCheck size={13} aria-hidden="true" />
                    永久关闭
                  </button>
                </>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </ContactAdContext.Provider>
  );
}

export function ContactAdTrigger() {
  const { openAd } = useContactAd();

  return (
    <button type="button" className="icon-button contact-ad-trigger" aria-label="消息通知" title="消息通知" onClick={openAd}>
      <Megaphone size={15} aria-hidden="true" />
    </button>
  );
}
