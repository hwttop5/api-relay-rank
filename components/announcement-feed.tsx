import { CalendarDays, ExternalLink, Info, ListOrdered } from "lucide-react";

import { AnnouncementContent, renderInlineAnnouncementText } from "@/components/announcement-markdown";
import { formatDateTime } from "@/lib/format";
import type { AnnouncementRow } from "@/lib/types";

export function AnnouncementFeed({ announcements, emptyText = "暂未抓到公开公告内容。" }: { announcements: AnnouncementRow[]; emptyText?: string }) {
  if (!announcements.length) {
    return (
      <div className="announcement">
        <div className="announcement-meta">
          <span className="inline-actions">
            <Info size={14} />
            公告
          </span>
        </div>
        <div className="announcement-content">{emptyText}</div>
      </div>
    );
  }

  return (
    <div className="stack">
      {announcements.map((announcement, index) => (
        <article className="announcement" key={`${announcement.id}-${announcement.publishedAt}-${index}`}>
          <div className="announcement-meta">
            <span className="inline-actions">
              <ListOrdered size={14} />
              {announcement.type || "default"}
              {announcement.extra ? <span className="announcement-extra">{renderInlineAnnouncementText(announcement.extra)}</span> : null}
            </span>
            <span className="inline-actions">
              <CalendarDays size={14} />
              {formatDateTime(announcement.publishedAt)}
            </span>
          </div>
          <AnnouncementContent content={announcement.content} contentHtml={announcement.contentHtml} />
          <div className="footer-note" style={{ marginTop: 10 }}>
            {announcement.sourceUrl ? (
              <a href={announcement.sourceUrl} target="_blank" rel="noreferrer" className="inline-actions station-link">
                <ExternalLink size={14} />
                <span>{announcement.sourceUrl}</span>
              </a>
            ) : (
              "来源：公开页面"
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
