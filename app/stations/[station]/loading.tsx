import { RouteLoadingState } from "@/components/route-status";

export default function StationLoading() {
  return <RouteLoadingState active="station" title="站点详情" description="正在加载站点档案和最新数据。" />;
}
