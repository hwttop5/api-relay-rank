/**
 * 页面浏览量统计 API
 * 提供站点的 PV 数据
 */
import { compressedJson } from '@/lib/response-compression';
import { getPageViewStats } from '@/lib/page-view-stats';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const stationKey = searchParams.get('station');

    const stats = await getPageViewStats();

    // 如果请求特定站点的 PV
    if (stationKey) {
      const pv = stats.stationPv[stationKey] ?? 0;
      return compressedJson({ pv, stationKey });
    }

    // 返回全部统计数据
    return compressedJson(stats);
  } catch (error) {
    console.error('Failed to get page view stats:', error);
    return compressedJson(
      { error: 'Failed to get page view stats' },
      { status: 500 }
    );
  }
}
