import { RouteLoadingState } from "@/components/route-status";

export default function StatementLoading() {
  return <RouteLoadingState active="statement" title="排名口径与特别声明" description="正在加载排名口径说明。" />;
}
