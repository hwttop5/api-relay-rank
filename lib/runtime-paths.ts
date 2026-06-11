import path from "node:path";

const APP_ROOT = process.cwd();
const DEFAULT_DATA_DIR = path.join(APP_ROOT, "data");
const DEFAULT_LIVE_AUTH_PROBE_DIR = path.join(APP_ROOT, "..", "tabbit-audit-profile");

export const DATA_DIR = process.env.APP_DATA_DIR
  ? path.resolve(process.env.APP_DATA_DIR)
  : DEFAULT_DATA_DIR;

export const SITE_DATA_PATH = path.join(DATA_DIR, "site-data.json");
export const PUBLIC_FETCH_DIR = path.join(DATA_DIR, "_public_fetch");
export const AUDIT_RUNS_ROOT = path.join(DATA_DIR, "_audit_runs");
export const LOCKS_DIR = path.join(DATA_DIR, "_locks");
export const OWNER_ANNOUNCEMENT_DIR = path.join(DATA_DIR, "_owner_announcement");
export const USER_UPLOADS_DIR = path.join(DATA_DIR, "_user_uploads");
export const ERROR_REPORT_UPLOADS_DIR = path.join(USER_UPLOADS_DIR, "error-reports");
export const OWNER_ANNOUNCEMENT_MANIFEST_PATH = path.join(OWNER_ANNOUNCEMENT_DIR, "manifest.json");
export const OWNER_ANNOUNCEMENT_ASSETS_DIR = path.join(OWNER_ANNOUNCEMENT_DIR, "assets");
export const OWNER_ANNOUNCEMENT_STATUS_PATH = path.join(OWNER_ANNOUNCEMENT_DIR, "status.json");
export const LIVE_AUTH_PROBE_DIR = process.env.LIVE_AUTH_PROBE_DIR
  ? path.resolve(process.env.LIVE_AUTH_PROBE_DIR)
  : path.resolve(DEFAULT_LIVE_AUTH_PROBE_DIR);

export function toLogicalDataPath(filePath: string) {
  const resolved = path.resolve(filePath);
  const dataRoot = path.resolve(DATA_DIR);
  if (resolved === dataRoot) {
    return "data";
  }
  if (resolved.startsWith(`${dataRoot}${path.sep}`)) {
    return path.posix.join("data", path.relative(dataRoot, resolved).replace(/\\/g, "/"));
  }
  return path.relative(APP_ROOT, resolved).replace(/\\/g, "/");
}

export function resolveLogicalDataPath(logicalPath: string) {
  const normalized = String(logicalPath || "").replace(/\\/g, "/").trim();
  if (!normalized || normalized === "data") {
    return DATA_DIR;
  }
  if (normalized.startsWith("data/")) {
    return path.join(DATA_DIR, normalized.slice("data/".length));
  }
  return path.join(APP_ROOT, normalized);
}

export function lockPath(name: string) {
  return path.join(LOCKS_DIR, `${name}.lock`);
}
