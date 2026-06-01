import type { ComponentPropsWithoutRef, ReactNode } from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

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

export function normalizeAnnouncementMarkdown(text: string) {
  return normalizeLegacyImageSyntax(decodeHtmlEntities(text)).replace(/\r\n?/g, "\n").trim();
}

export function renderInlineAnnouncementText(text: string) {
  return linkify(normalizeAnnouncementMarkdown(text));
}

function renderMarkdownContent(content: string) {
  const normalized = content.replace(/\r\n?/g, "\n").trim();
  if (!normalized) {
    return null;
  }

  return (
    <Markdown remarkPlugins={[remarkGfm]} skipHtml components={markdownComponents}>
      {normalizeAnnouncementMarkdown(normalized)}
    </Markdown>
  );
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
    return <p {...props}>{children}</p>;
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

export function AnnouncementMarkdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={mergeClassNames("announcement-content", className)}>
      {renderMarkdownContent(content)}
    </div>
  );
}

export function AnnouncementContent({ content, contentHtml, className }: { content: string; contentHtml?: string; className?: string }) {
  if (contentHtml?.trim()) {
    return (
      <div
        className={mergeClassNames("announcement-content", "announcement-content-html", className)}
        dangerouslySetInnerHTML={{ __html: contentHtml.trim() }}
      />
    );
  }

  return <AnnouncementMarkdown content={content} className={className} />;
}
