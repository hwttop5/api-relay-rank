"use client";

import { RouteErrorState } from "@/components/route-status";

export default function SubmitError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteErrorState active="submit" title="申请收录" description="申请页面暂时无法加载。" reset={reset} />;
}
