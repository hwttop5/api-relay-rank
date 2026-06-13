import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { PageViewTracker } from "@/components/page-view-tracker";
import { ServiceWorkerRegistration } from "@/components/service-worker-registration";
import {
  DEFAULT_DESCRIPTION,
  SITE_IMAGE_HEIGHT,
  SITE_IMAGE_PATH,
  SITE_IMAGE_WIDTH,
  SITE_TITLE,
  absoluteUrl,
  getSiteBaseUrl,
  safeJsonLd,
} from "@/lib/seo";

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
  manifest: "/manifest.webmanifest",
  title: {
    default: SITE_TITLE,
    template: `%s | ${SITE_TITLE}`,
  },
  description: DEFAULT_DESCRIPTION,
  applicationName: SITE_TITLE,
  alternates: {
    canonical: "/ranking",
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: SITE_TITLE,
  },
  icons: {
    apple: [
      {
        url: "/pwa/apple-touch-icon.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  },
  openGraph: {
    title: SITE_TITLE,
    description: DEFAULT_DESCRIPTION,
    url: "/ranking",
    siteName: SITE_TITLE,
    locale: "zh_CN",
    type: "website",
    images: [
      {
        url: SITE_IMAGE_PATH,
        width: SITE_IMAGE_WIDTH,
        height: SITE_IMAGE_HEIGHT,
        alt: SITE_TITLE,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: DEFAULT_DESCRIPTION,
    images: [SITE_IMAGE_PATH],
  },
};

export const viewport: Viewport = {
  themeColor: "#101820",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const webSiteJsonLd = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_TITLE,
    description: DEFAULT_DESCRIPTION,
    url: absoluteUrl("/ranking"),
  };
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
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(webSiteJsonLd) }} />
        <ServiceWorkerRegistration />
        <PageViewTracker />
        {children}
        {baiduTongjiScript ? (
          <script id="baidu-tongji" dangerouslySetInnerHTML={{ __html: baiduTongjiScript }} />
        ) : null}
      </body>
    </html>
  );
}
