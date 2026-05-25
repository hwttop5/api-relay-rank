import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DEFAULT_DESCRIPTION, SITE_TITLE, getSiteBaseUrl } from "@/lib/seo";

import "./globals.css";

const baiduTongjiId = process.env.NEXT_PUBLIC_BAIDU_TONGJI_ID?.trim();
const baiduTongjiScript =
  baiduTongjiId && /^[0-9a-f]{32}$/i.test(baiduTongjiId)
    ? `
var _hmt = window._hmt || [];
window._hmt = _hmt;
(function() {
  var hm = document.createElement("script");
  hm.src = "https://hm.baidu.com/hm.js?${baiduTongjiId.toLowerCase()}";
  var s = document.getElementsByTagName("script")[0];
  s.parentNode.insertBefore(hm, s);
})();
`
    : null;

export const metadata: Metadata = {
  metadataBase: new URL(getSiteBaseUrl()),
  title: {
    default: SITE_TITLE,
    template: `%s | ${SITE_TITLE}`,
  },
  description: DEFAULT_DESCRIPTION,
  applicationName: SITE_TITLE,
  alternates: {
    canonical: "/ranking",
  },
  openGraph: {
    title: SITE_TITLE,
    description: DEFAULT_DESCRIPTION,
    url: "/ranking",
    siteName: SITE_TITLE,
    locale: "zh_CN",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: DEFAULT_DESCRIPTION,
  },
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const themeScript = `
(() => {
  try {
    const stored = window.localStorage.getItem("api-relay-rank-theme");
    const theme = stored === "dark" || stored === "light"
      ? stored
      : (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  } catch {
    document.documentElement.dataset.theme = "dark";
  }
})();
`;

  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        {children}
        {baiduTongjiScript ? (
          <script id="baidu-tongji" dangerouslySetInnerHTML={{ __html: baiduTongjiScript }} />
        ) : null}
      </body>
    </html>
  );
}
