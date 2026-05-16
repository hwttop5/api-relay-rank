import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "中转站监视者",
  description: "api-relay-rank：查看中转站正式排名、全部档位倍率表与公开公告。",
  applicationName: "中转站监视者"
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
