import { RouteLoadingState } from "@/components/route-status";

export default function RankingLoading() {
  return <RouteLoadingState active="ranking" title="正式综合排名" description="正在读取最新排名和站点指标。" />;
}
