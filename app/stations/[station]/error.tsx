"use client";

import { RouteErrorState } from "@/components/route-status";

export default function StationError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteErrorState active="station" title="站点详情" description="站点详情暂时无法加载。" reset={reset} />;
}
