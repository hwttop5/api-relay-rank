import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { CalendarDays, ExternalLink, Info, ListOrdered } from "lucide-react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatDateTime } from "@/lib/format";
import type { AnnouncementRow } from "@/lib/types";

function mergeClassNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(" ");
}

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
      </a>,
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

function normalizeLegacyImageSyntax(text: string) {
  return text
    .replace(
      /^!image\s+(https?:\/\/\S+)(?:\s+(https?:\/\/\S+))?$/gim,
      (_match, imageUrl: string, href?: string) => {
        const token = `![image](${imageUrl})`;
        return href ? `[${token}](${href})` : token;
      },
    )
    .replace(
      /^!([^\s].*?)\s+(https?:\/\/\S+)(?:\s+(https?:\/\/\S+))?$/gim,
      (_match, rawAlt: string, imageUrl: string, href?: string) => {
        const alt = rawAlt.trim();
        const token = `![${alt}](${imageUrl})`;
        return href ? `[${token}](${href})` : token;
      },
    )
    .replace(
      /!\[\[([^\]]+)\]\((https?:\/\/[^)\s]+)\]\((https?:\/\/[^)\s]+)\)\)/g,
      (_match, alt: string, imageUrl: string, href: string) => `[![${alt}](${imageUrl})](${href})`,
    );
}

function normalizeMarkdownText(text: string) {
  return normalizeLegacyImageSyntax(decodeHtmlEntities(text)).replace(/\r\n?/g, "\n").trim();
}

function renderInlineMarkdown(text: string) {
  const decoded = normalizeMarkdownText(text);
  return linkify(decoded);
}

type MarkdownCodeProps = ComponentPropsWithoutRef<"code"> & {
  node?: unknown;
};

type MarkdownPreProps = ComponentPropsWithoutRef<"pre"> & {
  node?: unknown;
};

const markdownComponents: Components = {
  a({ href, children, node, ...props }) {
    return (
      <a href={href} target="_blank" rel="noreferrer" {...props}>
        {children}
      </a>
    );
  },
  p({ children, node, ...props }) {
    const firstChild = node?.children[0];
    if (
      node?.children.length === 1 &&
      firstChild?.type === "element" &&
      firstChild.tagName === "img"
    ) {
      return <figure className="announcement-image-wrap">{children}</figure>;
    }
    if (
      node?.children.length === 1 &&
      firstChild?.type === "element" &&
      firstChild.tagName === "a" &&
      firstChild.children.length === 1 &&
      firstChild.children[0]?.type === "element" &&
      firstChild.children[0].tagName === "img"
    ) {
      return <figure className="announcement-image-wrap">{children}</figure>;
    }
    return (
      <p {...props}>
        {children}
      </p>
    );
  },
  img({ src, alt, className, node, ...props }) {
    return (
      <img
        {...props}
        className={mergeClassNames("announcement-image", className)}
        src={src || ""}
        alt={alt || "announcement image"}
        loading="lazy"
      />
    );
  },
  h1({ children, className, node, ...props }) {
    return (
      <h3 className={mergeClassNames("announcement-heading", className)} {...props}>
        {children}
      </h3>
    );
  },
  h2({ children, className, node, ...props }) {
    return (
      <h4 className={mergeClassNames("announcement-heading", className)} {...props}>
        {children}
      </h4>
    );
  },
  h3({ children, className, node, ...props }) {
    return (
      <h5 className={mergeClassNames("announcement-heading", className)} {...props}>
        {children}
      </h5>
    );
  },
  h4({ children, className, node, ...props }) {
    return (
      <h5 className={mergeClassNames("announcement-heading", className)} {...props}>
        {children}
      </h5>
    );
  },
  hr({ className, node, ...props }) {
    return <hr className={mergeClassNames("announcement-divider", className)} {...props} />;
  },
  ul({ children, className, node, ...props }) {
    return (
      <ul className={mergeClassNames("announcement-list", className)} {...props}>
        {children}
      </ul>
    );
  },
  ol({ children, className, node, ...props }) {
    return (
      <ol className={mergeClassNames("announcement-list", className)} {...props}>
        {children}
      </ol>
    );
  },
  blockquote({ children, className, node, ...props }) {
    return (
      <blockquote className={mergeClassNames("announcement-quote", className)} {...props}>
        {children}
      </blockquote>
    );
  },
  table({ children, className, node, ...props }) {
    return (
      <div className="announcement-table-wrap">
        <table className={mergeClassNames("announcement-table", className)} {...props}>
          {children}
        </table>
      </div>
    );
  },
  pre({ children, className, node, ...props }: MarkdownPreProps) {
    return (
      <pre className={mergeClassNames("announcement-code-block", className)} {...props}>
        {children}
      </pre>
    );
  },
  code({ children, className, node, ...props }: MarkdownCodeProps) {
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
};

function renderMarkdownContent(text: string) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={markdownComponents}
    >
      {normalizeMarkdownText(text)}
    </Markdown>
  );
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
          <div className="announcement-content">{renderMarkdownContent(announcement.content)}</div>
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
