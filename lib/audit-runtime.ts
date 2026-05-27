import { access, cp, mkdir, open, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import dns from "node:dns/promises";
import net from "node:net";
import path from "node:path";

import {
  AUDIT_RUNS_ROOT,
  DATA_DIR,
  LIVE_AUTH_PROBE_DIR,
  LOCKS_DIR,
  OWNER_ANNOUNCEMENT_ASSETS_DIR,
  OWNER_ANNOUNCEMENT_DIR,
  PUBLIC_FETCH_DIR,
  lockPath,
} from "./runtime-paths";

const CLOUD_METADATA_HOSTS = new Set([
  "169.254.169.254",
  "100.100.100.200",
  "metadata.google.internal",
  "metadata",
]);

export class AuditTargetError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AuditTargetError";
    this.status = status;
  }
}

function isLoopbackLike(hostname: string) {
  const lowered = hostname.toLowerCase();
  return lowered === "localhost" || lowered === "::1" || lowered === "127.0.0.1";
}

function isForbiddenHostname(hostname: string) {
  const lowered = hostname.toLowerCase();
  return (
    isLoopbackLike(lowered) ||
    lowered.endsWith(".local") ||
    lowered.endsWith(".internal") ||
    CLOUD_METADATA_HOSTS.has(lowered)
  );
}

function isPrivateOrReservedIp(ip: string) {
  if (!net.isIP(ip)) {
    return false;
  }
  if (net.isIPv4(ip)) {
    const [a, b, c] = ip.split(".").map(Number);
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 0 && (c === 0 || c === 2)) ||
      (a === 192 && b === 88 && c === 99) ||
      (a === 192 && b === 168) ||
      (a === 198 && (b === 18 || b === 19)) ||
      (a === 198 && b === 51 && c === 100) ||
      (a === 203 && b === 0 && c === 113) ||
      a >= 224
    );
  }
  const lowered = ip.toLowerCase();
  return (
    lowered === "::1" ||
    lowered === "::" ||
    lowered.startsWith("2001:db8:") ||
    lowered.startsWith("fc") ||
    lowered.startsWith("fd") ||
    lowered.startsWith("fe80:") ||
    lowered.startsWith("fec0:") ||
    lowered.startsWith("::ffff:127.") ||
    lowered.startsWith("::ffff:169.254.") ||
    lowered.startsWith("::ffff:10.") ||
    lowered.startsWith("::ffff:192.168.") ||
    /^::ffff:100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(lowered) ||
    /^::ffff:172\.(1[6-9]|2\d|3[0-1])\./.test(lowered) ||
    /^::ffff:192\.0\.(0|2)\./.test(lowered) ||
    lowered.startsWith("::ffff:192.88.99.") ||
    /^::ffff:198\.(1[89]|51\.100)\./.test(lowered) ||
    lowered.startsWith("::ffff:203.0.113.")
  );
}

export async function assertPublicAuditTarget(rawUrl: string) {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new AuditTargetError("apiBaseUrl must be a valid absolute URL.", 400);
  }

  const hostname = parsed.hostname.replace(/\.$/, "").toLowerCase();
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new AuditTargetError("apiBaseUrl must use http or https.", 400);
  }
  if (parsed.username || parsed.password) {
    throw new AuditTargetError("apiBaseUrl must not contain embedded credentials.", 400);
  }
  if (!hostname) {
    throw new AuditTargetError("apiBaseUrl must include a hostname.", 400);
  }
  if (isForbiddenHostname(hostname)) {
    throw new AuditTargetError("apiBaseUrl must target a public host.", 403);
  }
  if (net.isIP(hostname) && isPrivateOrReservedIp(hostname)) {
    throw new AuditTargetError("apiBaseUrl must not target a private or reserved IP.", 403);
  }

  const resolved = await dns.lookup(hostname, { all: true, verbatim: true });
  if (!resolved.length) {
    throw new AuditTargetError("apiBaseUrl hostname did not resolve.", 403);
  }
  for (const entry of resolved) {
    if (isPrivateOrReservedIp(entry.address)) {
      throw new AuditTargetError("apiBaseUrl resolved to a private or reserved IP.", 403);
    }
  }

  return parsed.toString();
}

export async function ensureRuntimeDirectories() {
  await Promise.all([
    mkdir(DATA_DIR, { recursive: true }),
    mkdir(PUBLIC_FETCH_DIR, { recursive: true }),
    mkdir(AUDIT_RUNS_ROOT, { recursive: true }),
    mkdir(OWNER_ANNOUNCEMENT_DIR, { recursive: true }),
    mkdir(OWNER_ANNOUNCEMENT_ASSETS_DIR, { recursive: true }),
    mkdir(LIVE_AUTH_PROBE_DIR, { recursive: true }),
    mkdir(LOCKS_DIR, { recursive: true }),
  ]);
}

export async function tryAcquireLock(name: string, staleMs = 0) {
  await ensureRuntimeDirectories();
  const filePath = lockPath(name);
  try {
    const handle = await open(filePath, "wx");
    await handle.writeFile(
      JSON.stringify(
        {
          name,
          pid: process.pid,
          createdAt: new Date().toISOString(),
        },
        null,
        2,
      ),
      "utf8",
    );
    return {
      path: filePath,
      async release() {
        await handle.close();
        await rm(filePath, { force: true });
      },
    };
  } catch {
    if (staleMs > 0) {
      try {
        const info = await stat(filePath);
        if (Date.now() - info.mtimeMs >= staleMs) {
          await rm(filePath, { force: true });
          return await tryAcquireLock(name, 0);
        }
      } catch {
        return await tryAcquireLock(name, 0);
      }
    }
    return null;
  }
}

export async function withExclusiveLock<T>(name: string, task: () => Promise<T>, staleMs = 0) {
  const lock = await tryAcquireLock(name, staleMs);
  if (!lock) {
    throw new Error(`LOCK_HELD:${name}`);
  }
  try {
    return await task();
  } finally {
    await lock.release();
  }
}

async function directoryHasEntries(folder: string) {
  try {
    const entries = await readdir(folder);
    return entries.length > 0;
  } catch {
    return false;
  }
}

async function copyDirectoryContents(sourceDir: string, targetDir: string) {
  await mkdir(targetDir, { recursive: true });
  const entries = await readdir(sourceDir);
  for (const entry of entries) {
    await cp(path.join(sourceDir, entry), path.join(targetDir, entry), { recursive: true, force: false });
  }
}

export async function seedRuntimeDataFromRepo() {
  const repoSiteData = path.join(process.cwd(), "data", "site-data.json");
  const runtimeSiteData = path.resolve(path.join(DATA_DIR, "site-data.json"));
  const repoFetchDir = path.join(process.cwd(), "data", "_public_fetch");
  const runtimeFetchDir = path.resolve(PUBLIC_FETCH_DIR);
  const repoOwnerAnnouncementDir = path.join(process.cwd(), "data", "_owner_announcement");
  const runtimeOwnerAnnouncementDir = path.resolve(OWNER_ANNOUNCEMENT_DIR);
  const sameSiteDataPath = path.resolve(repoSiteData) === runtimeSiteData;
  const sameFetchDir = path.resolve(repoFetchDir) === runtimeFetchDir;
  const sameOwnerAnnouncementDir = path.resolve(repoOwnerAnnouncementDir) === runtimeOwnerAnnouncementDir;

  await ensureRuntimeDirectories();
  if (!sameSiteDataPath) {
    try {
      await access(runtimeSiteData);
    } catch {
      const payload = await readFile(repoSiteData, "utf8");
      await writeFile(runtimeSiteData, payload, "utf8");
    }
  }
  if (!sameFetchDir) {
    try {
      await access(repoFetchDir);
      if (!(await directoryHasEntries(runtimeFetchDir))) {
        await copyDirectoryContents(repoFetchDir, runtimeFetchDir);
      }
    } catch {}
  }
  if (!sameOwnerAnnouncementDir) {
    try {
      await access(repoOwnerAnnouncementDir);
      if (!(await directoryHasEntries(runtimeOwnerAnnouncementDir))) {
        await copyDirectoryContents(repoOwnerAnnouncementDir, runtimeOwnerAnnouncementDir);
      }
    } catch {}
  }
}
