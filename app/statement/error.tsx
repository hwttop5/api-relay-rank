"use client";

import { RouteErrorState } from "@/components/route-status";

export default function StatementError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteErrorState active="statement" title="排名口径与特别声明" description="声明内容暂时无法加载。" reset={reset} />;
}
