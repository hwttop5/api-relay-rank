import type { ReactNode } from "react";
import { CalendarDays, ExternalLink, Info, ListOrdered } from "lucide-react";

import { formatDateTime } from "@/lib/format";
import type { AnnouncementRow } from "@/lib/types";

function linkify(text: string) {
  const regex = /(https?:\/\/[^\s<>()]+|www\.[^\s<>()]+)/g;
  const parts: ReactNode[] = [];
  let lastIndex = 0;

  text.replace(regex, (match, _group, offset) => {
    if (offset > lastIndex) {
      parts.push(text.slice(lastIndex, offset));
    }
    const href = match.startsWith("http") ? match : `https://${match}`;
    parts.push(
      <a key={`${offset}-${match}`} href={href} target="_blank" rel="noreferrer">
        {match}
      </a>
    );
    lastIndex = offset + match.length;
    return match;
  });

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length ? parts : [text];
}

function decodeHtmlEntities(text: string) {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

function renderHtmlAnchors(text: string) {
  const decoded = decodeHtmlEntities(text);
  const anchorRegex = /<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)<\/a>/gis;
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = anchorRegex.exec(decoded)) !== null) {
    const [raw, href, label] = match;
    const start = match.index;

    if (start > lastIndex) {
      parts.push(...linkify(decoded.slice(lastIndex, start)));
    }

    parts.push(
      <a key={`${start}-${href}`} href={href} target="_blank" rel="noreferrer">
        {label || href}
      </a>
    );

    lastIndex = start + raw.length;
  }

  if (!parts.length) {
    return linkify(decoded);
  }

  if (lastIndex < decoded.length) {
    parts.push(...linkify(decoded.slice(lastIndex)));
  }

  return parts;
}

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
              {announcement.extra ? <span className="announcement-extra">{renderHtmlAnchors(announcement.extra)}</span> : null}
            </span>
            <span className="inline-actions">
              <CalendarDays size={14} />
              {formatDateTime(announcement.publishedAt)}
            </span>
          </div>
          <div className="announcement-content">{renderHtmlAnchors(announcement.content)}</div>
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
