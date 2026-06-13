/**
 * 骨架屏组件 - 用于数据加载时的占位显示
 * 提升感知性能，改善用户体验
 */

export function TableRowSkeleton() {
  return (
    <tr className="skeleton-row">
      <td><div className="skeleton skeleton-text" /></td>
      <td><div className="skeleton skeleton-text" /></td>
      <td><div className="skeleton skeleton-text" /></td>
      <td><div className="skeleton skeleton-text" /></td>
      <td><div className="skeleton skeleton-text" /></td>
      <td><div className="skeleton skeleton-text" /></td>
    </tr>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <tbody>
      {Array.from({ length: rows }).map((_, i) => (
        <TableRowSkeleton key={i} />
      ))}
    </tbody>
  );
}

export function CardSkeleton() {
  return (
    <div className="mobile-card skeleton-card">
      <div className="mobile-card-header">
        <div className="mobile-card-lead">
          <div className="skeleton skeleton-rank" />
          <div className="mobile-card-title-block">
            <div className="skeleton skeleton-title" />
            <div className="skeleton skeleton-subtitle" />
          </div>
        </div>
      </div>
      <div className="mobile-metrics-grid">
        <div className="mobile-metric">
          <div className="skeleton skeleton-text" style={{ width: '60%' }} />
          <div className="skeleton skeleton-text" style={{ width: '80%', marginTop: '8px' }} />
        </div>
        <div className="mobile-metric">
          <div className="skeleton skeleton-text" style={{ width: '60%' }} />
          <div className="skeleton skeleton-text" style={{ width: '80%', marginTop: '8px' }} />
        </div>
      </div>
    </div>
  );
}

export function CardListSkeleton({ cards = 3 }: { cards?: number }) {
  return (
    <div className="mobile-card-list">
      {Array.from({ length: cards }).map((_, i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  );
}

export function DetailCardSkeleton() {
  return (
    <div className="detail-card">
      <div className="skeleton skeleton-text" style={{ width: '40%', height: '14px' }} />
      <div className="skeleton skeleton-text" style={{ width: '90%', height: '12px', marginTop: '10px' }} />
      <div className="skeleton skeleton-text" style={{ width: '75%', height: '12px', marginTop: '6px' }} />
    </div>
  );
}

export function SectionSkeleton() {
  return (
    <div className="section">
      <div className="section-head">
        <div className="skeleton skeleton-title" style={{ width: '200px', height: '20px' }} />
      </div>
      <div className="section-body">
        <div className="skeleton skeleton-text" style={{ width: '100%', height: '14px' }} />
        <div className="skeleton skeleton-text" style={{ width: '90%', height: '14px', marginTop: '10px' }} />
        <div className="skeleton skeleton-text" style={{ width: '85%', height: '14px', marginTop: '10px' }} />
      </div>
    </div>
  );
}
