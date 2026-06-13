"use client";

import { RouteErrorState } from "@/components/route-status";

export default function AuditError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteErrorState active="audit" title="安全审计" description="审计页面暂时无法加载。" reset={reset} />;
}
