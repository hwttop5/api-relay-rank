import { ClipboardCheck, FileText, ShieldCheck, Trophy, type LucideIcon } from "lucide-react";

export type AppNavKey = "ranking" | "audit" | "submit" | "statement" | "station";

export const NAV_ITEMS = [
  { key: "ranking", href: "/ranking", label: "综合排名", icon: Trophy },
  { key: "audit", href: "/audit", label: "安全审计", icon: ShieldCheck },
  { key: "submit", href: "/submit", label: "申请收录", icon: ClipboardCheck },
  { key: "statement", href: "/statement", label: "特别声明", icon: FileText }
] as const satisfies ReadonlyArray<{
  key: Exclude<AppNavKey, "station">;
  href: string;
  label: string;
  icon: LucideIcon;
}>;
