import { RouteLoadingState } from "@/components/route-status";

export default function SubmitLoading() {
  return <RouteLoadingState active="submit" title="申请收录" description="正在加载申请表单。" />;
}
