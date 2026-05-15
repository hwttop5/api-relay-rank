import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "中转站监视者",
  description: "api-relay-rank：查看中转站正式排名、全部档位倍率表与公开公告。",
  applicationName: "中转站监视者"
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
