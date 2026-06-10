export const SITE_TOTAL_IMPORT_PATH = "__site_total__";

export interface NormalizedPageViewPath {
  canonicalPath: string;
  stationKey: string | null;
}

function stripQueryAndHash(value: string) {
  const marker = value.search(/[?#]/);
  return marker >= 0 ? value.slice(0, marker) : value;
}

function decodeSegment(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return "";
  }
}

export function normalizePageViewPath(rawPath: unknown): NormalizedPageViewPath | null {
  if (typeof rawPath !== "string") {
    return null;
  }

  let path = rawPath.trim();
  if (!path) {
    return null;
  }

  if (/^https?:\/\//i.test(path)) {
    try {
      path = new URL(path).pathname;
    } catch {
      return null;
    }
  } else {
    path = stripQueryAndHash(path);
  }

  if (!path.startsWith("/")) {
    return null;
  }

  path = path.replace(/\/{2,}/g, "/");
  if (path.length > 1) {
    path = path.replace(/\/+$/, "");
  }

  const lowerPath = path.toLowerCase();
  if (lowerPath === "/") {
    return { canonicalPath: "/ranking", stationKey: null };
  }
  if (lowerPath === "/ranking" || lowerPath === "/audit" || lowerPath === "/statement") {
    return { canonicalPath: lowerPath, stationKey: null };
  }
  if (lowerPath === "/api" || lowerPath.startsWith("/api/") || lowerPath.startsWith("/_next/")) {
    return null;
  }

  const stationMatch = path.match(/^\/stations\/([^/]+)$/);
  if (stationMatch) {
    const stationKey = decodeSegment(stationMatch[1]);
    if (!/^[A-Za-z0-9._-]{1,160}$/.test(stationKey)) {
      return null;
    }
    return { canonicalPath: `/stations/${stationKey}`, stationKey };
  }

  if (/\.[A-Za-z0-9]{1,8}$/.test(path)) {
    return null;
  }

  return null;
}
