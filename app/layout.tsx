import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DEFAULT_DESCRIPTION, SITE_TITLE, getSiteBaseUrl } from "@/lib/seo";

import "./globals.css";

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
      </body>
    </html>
  );
}
