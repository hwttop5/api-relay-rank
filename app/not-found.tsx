import Link from "next/link";

export default function NotFound() {
  return (
    <main className="app-shell">
      <div className="page-shell">
        <section className="section">
          <div className="section-head">
            <div>
              <h1 className="section-title">页面不存在</h1>
              <p className="section-desc">当前站点详情尚未收录，或者链接已经失效。</p>
            </div>
          </div>
          <div className="section-body">
            <Link href="/" className="tiny-button">
              返回首页
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
