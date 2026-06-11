"use client";

import { useEffect, useState } from "react";

const SITE_STARTED_AT = new Date("2026-05-17T01:18:00+08:00").getTime();
const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

function formatUptime(now: number) {
  const elapsed = Math.max(0, now - SITE_STARTED_AT);
  const days = Math.floor(elapsed / DAY_MS);
  const hours = Math.floor((elapsed % DAY_MS) / HOUR_MS);
  const minutes = Math.floor((elapsed % HOUR_MS) / MINUTE_MS);
  const seconds = Math.floor((elapsed % MINUTE_MS) / SECOND_MS);
  const pad = (value: number) => String(value).padStart(2, "0");

  return `站点已运行 ${days} 天 ${pad(hours)} 小时 ${pad(minutes)} 分 ${pad(seconds)} 秒`;
}

export function SiteUptime() {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, SECOND_MS);

    return () => window.clearInterval(timer);
  }, []);

  return <span className="site-uptime">{now === null ? "站点已运行 -- 天 -- 小时 -- 分 -- 秒" : formatUptime(now)}</span>;
}
