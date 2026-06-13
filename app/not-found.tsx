import Link from "next/link";
import { Home, ArrowLeft, Search, Compass } from "lucide-react";

export default function NotFound() {
  return (
    <main className="app-shell">
      <div className="page-shell">
        <div className="not-found-container">
          {/* 404 大标题 */}
          <div className="not-found-hero">
            <div className="not-found-number">
              <span className="not-found-digit">4</span>
              <span className="not-found-digit not-found-digit-middle">0</span>
              <span className="not-found-digit">4</span>
            </div>
            <div className="not-found-waves">
              <div className="not-found-wave"></div>
              <div className="not-found-wave"></div>
              <div className="not-found-wave"></div>
            </div>
          </div>

          {/* 内容区域 */}
          <div className="not-found-content">
            <h1 className="not-found-title">页面走丢了</h1>
            <p className="not-found-description">
              抱歉，您访问的页面不存在或已被移除。
              <br />
              可能是链接失效，或者该站点详情尚未收录。
            </p>

            {/* 操作按钮 */}
            <div className="not-found-actions">
              <Link href="/" className="not-found-button not-found-button-primary">
                <Home size={18} />
                返回首页
              </Link>
              <Link href="/ranking" className="not-found-button not-found-button-secondary">
                <Compass size={18} />
                查看排名
              </Link>
            </div>

            {/* 建议 */}
            <div className="not-found-suggestions">
              <h3 className="not-found-suggestions-title">您可以尝试：</h3>
              <ul className="not-found-suggestions-list">
                <li>
                  <Search size={16} />
                  检查 URL 是否正确
                </li>
                <li>
                  <ArrowLeft size={16} />
                  返回上一页
                </li>
                <li>
                  <Home size={16} />
                  从首页重新开始
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
