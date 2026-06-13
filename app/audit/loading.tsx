import { RouteLoadingState } from "@/components/route-status";

export default function AuditLoading() {
  return <RouteLoadingState active="audit" title="安全审计" description="正在加载审计入口和历史记录。" />;
}
