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
    .replace(/&nbsp;/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

function stripHtmlTags(text: string) {
  return decodeHtmlEntities(text)
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|h[1-6]|li|ul|ol|blockquote|tr)>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function renderInlineMarkdown(text: string) {
  const decoded = stripHtmlTags(text);
  const inlineRegex = /(\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
  const parts: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = inlineRegex.exec(decoded)) !== null) {
    const [raw, _markdownLink, linkLabel, linkHref, codeText, strongText] = match;
    const start = match.index;

    if (start > lastIndex) {
      parts.push(...linkify(decoded.slice(lastIndex, start)));
    }

    if (linkHref) {
      parts.push(
        <a key={`${start}-${linkHref}`} href={linkHref} target="_blank" rel="noreferrer">
          {linkLabel || linkHref}
        </a>
      );
    } else if (codeText) {
      parts.push(<code key={`${start}-code`}>{codeText}</code>);
    } else if (strongText) {
      parts.push(<strong key={`${start}-strong`}>{strongText}</strong>);
    }

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

function isTableSeparator(line: string) {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line);
}

function splitTableRow(line: string) {
  return line
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderMarkdownBlocks(text: string) {
  const normalized = stripHtmlTags(text).replace(/\r\n?/g, "\n");
  const lines = normalized.split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const rawLine = lines[index] ?? "";
    const line = rawLine.trim();

    if (!line) {
      index += 1;
      continue;
    }

    if (line.includes("|") && isTableSeparator(lines[index + 1]?.trim() ?? "")) {
      const headers = splitTableRow(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push(
        <div className="announcement-table-wrap" key={`table-${key++}`}>
          <table className="announcement-table">
            <thead>
              <tr>
                {headers.map((header, cellIndex) => (
                  <th key={`h-${cellIndex}`}>{renderInlineMarkdown(header)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`r-${rowIndex}`}>
                  {headers.map((_, cellIndex) => (
                    <td key={`c-${cellIndex}`}>{renderInlineMarkdown(row[cellIndex] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const headingKey = `heading-${key++}`;
      const headingBody = renderInlineMarkdown(heading[2]);
      if (level <= 1) {
        blocks.push(<h3 className="announcement-heading" key={headingKey}>{headingBody}</h3>);
      } else if (level === 2) {
        blocks.push(<h4 className="announcement-heading" key={headingKey}>{headingBody}</h4>);
      } else {
        blocks.push(<h5 className="announcement-heading" key={headingKey}>{headingBody}</h5>);
      }
      index += 1;
      continue;
    }

    if (/^-{3,}$/.test(line)) {
      blocks.push(<hr className="announcement-divider" key={`hr-${key++}`} />);
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      const ordered = /^\d+\.\s+/.test(line);
      const items: string[] = [];
      while (index < lines.length) {
        const candidate = lines[index].trim();
        const match = ordered ? /^\d+\.\s+(.+)$/.exec(candidate) : /^[-*]\s+(.+)$/.exec(candidate);
        if (!match) {
          break;
        }
        items.push(match[1]);
        index += 1;
      }
      const ListTag = (ordered ? "ol" : "ul") as "ol" | "ul";
      blocks.push(
        <ListTag className="announcement-list" key={`list-${key++}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInlineMarkdown(item)}</li>
          ))}
        </ListTag>
      );
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length) {
      const candidate = lines[index].trim();
      if (
        !candidate ||
        /^(#{1,4})\s+/.test(candidate) ||
        /^[-*]\s+/.test(candidate) ||
        /^\d+\.\s+/.test(candidate) ||
        /^-{3,}$/.test(candidate) ||
        (candidate.includes("|") && isTableSeparator(lines[index + 1]?.trim() ?? ""))
      ) {
        break;
      }
      paragraph.push(candidate);
      index += 1;
    }
    blocks.push(
      <p key={`p-${key++}`}>
        {renderInlineMarkdown(paragraph.join("\n"))}
      </p>
    );
  }

  return blocks.length ? blocks : renderInlineMarkdown(normalized);
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
              {announcement.extra ? <span className="announcement-extra">{renderInlineMarkdown(announcement.extra)}</span> : null}
            </span>
            <span className="inline-actions">
              <CalendarDays size={14} />
              {formatDateTime(announcement.publishedAt)}
            </span>
          </div>
          <div className="announcement-content">{renderMarkdownBlocks(announcement.content)}</div>
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
