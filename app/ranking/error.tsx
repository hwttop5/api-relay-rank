"use client";

import { RouteErrorState } from "@/components/route-status";

export default function RankingError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteErrorState active="ranking" title="正式综合排名" description="排名数据暂时无法加载。" reset={reset} />;
}
