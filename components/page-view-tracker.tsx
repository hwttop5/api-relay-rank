"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

let lastSentPath: string | null = null;

export function PageViewTracker() {
  const pathname = usePathname();

  useEffect(() => {
    if (!pathname || lastSentPath === pathname) {
      return;
    }
    lastSentPath = pathname;

    const body = JSON.stringify({ path: pathname });
    const endpoint = "/api/page-view";
    if (navigator.sendBeacon) {
      const ok = navigator.sendBeacon(endpoint, new Blob([body], { type: "application/json" }));
      if (ok) {
        return;
      }
    }

    void fetch(endpoint, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => undefined);
  }, [pathname]);

  return null;
}
