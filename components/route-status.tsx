import { AlertTriangle, RefreshCw } from "lucide-react";

import { AppShell, StatusChip } from "@/components/app-shell";
import type { AppNavKey } from "@/components/nav-items";
import type { ShellData } from "@/lib/types";

const FALLBACK_SHELL_DATA: ShellData = {
  generatedAt: "",
  projectName: "AI中转站监视者",
  siteName: "AI中转站监视者",
};

export function RouteLoadingState({ active, title, description }: { active: AppNavKey; title: string; description: string }) {
  return (
    <AppShell active={active} data={FALLBACK_SHELL_DATA}>
      <section className="section">
        <div className="section-head">
          <div>
            <h1 className="section-title">{title}</h1>
            <p className="section-desc">{description}</p>
          </div>
          <StatusChip label="加载中" tone="blue" />
        </div>
        <div className="section-body">
          <div className="route-loading-container" role="status" aria-live="polite">
            {/* 加载动画 */}
            <div className="route-loading-spinner">
              <div className="spinner-ring"></div>
              <div className="spinner-ring spinner-ring-2"></div>
              <div className="spinner-dot"></div>
            </div>

            {/* 加载文本 */}
            <div className="route-loading-content">
              <h3 className="route-loading-title">正在加载数据</h3>
              <p className="route-loading-desc">
                正在从服务器获取最新数据，请稍候...
              </p>
            </div>

            {/* 进度指示器 */}
            <div className="route-loading-progress">
              <div className="route-loading-progress-bar"></div>
            </div>
          </div>
        </div>
      </section>
    </AppShell>
  );
}

export function RouteErrorState({ active, title, description, reset }: { active: AppNavKey; title: string; description: string; reset: () => void }) {
  return (
    <AppShell active={active} data={FALLBACK_SHELL_DATA}>
      <section className="section">
        <div className="section-head">
          <div>
            <h1 className="section-title">{title}</h1>
            <p className="section-desc">{description}</p>
          </div>
          <StatusChip label="加载失败" tone="danger" />
        </div>
        <div className="section-body">
          <div className="route-status-card route-status-card-error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <div>
              <p className="route-status-title">出错了</p>
              <p className="section-desc">页面暂时无法加载，可以稍后重试。</p>
            </div>
            <button type="button" className="tiny-button" onClick={reset}>
              <RefreshCw size={14} aria-hidden="true" />
              重试
            </button>
          </div>
        </div>
      </section>
    </AppShell>
  );
}
