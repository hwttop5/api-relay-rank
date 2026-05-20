import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { revalidatePath } from "next/cache";

import { getSiteData } from "@/lib/site-data";
import type { SiteData, StationAuditSummary } from "@/lib/types";

const execFileAsync = promisify(execFile);
const APP_ROOT = process.cwd();
const AUDIT_TIMEOUT_MS = 1000 * 60 * 20;

interface AuditRunPayload {
  apiBaseUrl?: unknown;
  apiKey?: unknown;
  model?: unknown;
}

function jsonResponse(payload: unknown, status = 200) {
  return Response.json(payload, {
    status,
    headers: {
      "cache-control": "no-store",
    },
  });
}

function sanitizeAuditDetail(value: unknown, secrets: string[] = []) {
  let text = value instanceof Error ? value.message : String(value || "");
  for (const secret of secrets) {
    if (secret) {
      text = text.split(secret).join("<redacted>");
    }
  }
  text = text.replace(/(authorization\s*:\s*bearer\s+)[^\s"']+/gi, "$1<redacted>");
  text = text.replace(/(bearer\s+)[A-Za-z0-9._\-+/=]{8,}/gi, "$1<redacted>");
  text = text.replace(/\bsk-[A-Za-z0-9._\-]{6,}\b/g, "sk-<redacted>");
  text = text.replace(/([A-Za-z]:\\Users\\)([^\\\r\n`"']+)/g, "$1xxx");
  text = text.replace(/\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b/g, "xxx");
  text = text.replace(/ttop5/gi, "xxx");
  return text;
}

function normalizeOrigin(value: string) {
  const url = new URL(value);
  return url.origin.toLowerCase();
}

function slugifyStationKey(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/^www\./, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "relay";
}

function getStationOrigins(station: SiteData["stations"][number]) {
  const origins = new Set<string>();
  for (const value of [station.url, ...(station.audits?.latestByModel.map((item) => item.auditedBaseUrl) ?? [])]) {
    if (!value) {
      continue;
    }
    try {
      origins.add(normalizeOrigin(value));
    } catch {
      // Ignore malformed historical URLs instead of making ad-hoc audits unusable.
    }
  }
  return origins;
}

function resolveStation(siteData: SiteData, apiBaseUrl: string) {
  const origin = normalizeOrigin(apiBaseUrl);
  const matches = siteData.stations.filter((station) => getStationOrigins(station).has(origin));
  return { origin, matches };
}

function deriveUnlistedStationKey(siteData: SiteData, apiBaseUrl: string) {
  const url = new URL(apiBaseUrl);
  const baseKey = `audit-${slugifyStationKey(url.host || url.hostname)}`;
  const existingKeys = new Set(siteData.stations.map((station) => station.key));
  if (!existingKeys.has(baseKey)) {
    return baseKey;
  }

  for (let suffix = 2; suffix < 100; suffix += 1) {
    const candidate = `${baseKey}-${suffix}`;
    if (!existingKeys.has(candidate)) {
      return candidate;
    }
  }

  return `${baseKey}-${Date.now()}`;
}

function runPythonJson(args: string[], env?: Record<string, string>) {
  return execFileAsync("python", args, {
    cwd: APP_ROOT,
    env: { ...process.env, ...env },
    maxBuffer: 1024 * 1024 * 8,
    timeout: AUDIT_TIMEOUT_MS,
  });
}

export async function POST(request: Request) {
  let payload: AuditRunPayload;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse({ error: "Request body must be valid JSON." }, 400);
  }

  const apiBaseUrl = typeof payload.apiBaseUrl === "string" ? payload.apiBaseUrl.trim() : "";
  const apiKey = typeof payload.apiKey === "string" ? payload.apiKey.trim() : "";
  const model = typeof payload.model === "string" ? payload.model.trim() : "";

  if (!apiBaseUrl || !apiKey || !model) {
    return jsonResponse({ error: "apiBaseUrl, apiKey and model are required." }, 400);
  }

  let siteData = await getSiteData();
  let stationKey: string;
  try {
    const { matches } = resolveStation(siteData, apiBaseUrl);
    if (matches.length === 0) {
      stationKey = deriveUnlistedStationKey(siteData, apiBaseUrl);
    } else if (matches.length > 1) {
      return jsonResponse({ error: `Multiple stations match this API origin: ${matches.map((item) => item.key).join(", ")}.` }, 409);
    } else {
      stationKey = matches[0].key;
    }
  } catch {
    return jsonResponse({ error: "apiBaseUrl must be a valid absolute URL." }, 400);
  }

  let executed: Array<{ station: string; model: string; summary: string; report: string }>;
  try {
    const script = [
      "scripts/run_station_audit.py",
      "--station",
      stationKey,
      "--model",
      model,
      "--ad-hoc-target",
      "--override-base-url",
      apiBaseUrl,
      "--request-api-key-env",
      "STATION_AUDIT_REQUEST_KEY",
    ];
    const { stdout } = await runPythonJson(script, { STATION_AUDIT_REQUEST_KEY: apiKey });
    const result = JSON.parse(stdout) as { executed?: Array<{ station: string; model: string; summary: string; report: string }> };
    executed = result.executed ?? [];
  } catch (error) {
    return jsonResponse({ error: "Audit engine failed.", detail: sanitizeAuditDetail(error, [apiKey]) }, 502);
  }

  if (!executed[0]?.summary) {
    return jsonResponse({ error: "Audit completed without a summary path." }, 502);
  }

  try {
    await runPythonJson(["scripts/build_site_data.py"]);
    siteData = await getSiteData();
  } catch (error) {
    return jsonResponse({ error: "Failed to rebuild site data.", detail: sanitizeAuditDetail(error, [apiKey]) }, 500);
  }

  revalidatePath("/");
  revalidatePath("/ranking");
  revalidatePath("/audit");
  revalidatePath("/statement");
  revalidatePath(`/stations/${encodeURIComponent(stationKey)}`);
  revalidatePath("/sitemap.xml");

  const station = siteData.stations.find((item) => item.key === stationKey);
  const summary = station?.audits?.latestByModel.find((item) => item.model === model) as StationAuditSummary | undefined;
  if (!station || !summary) {
    return jsonResponse({ error: "Audit summary was archived but not found in rebuilt site data." }, 500);
  }

  return jsonResponse({
    station: station.key,
    model,
    summary,
    stationUrl: `/stations/${encodeURIComponent(station.key)}#audit`,
    reportUrl: `/api/audit-report?station=${encodeURIComponent(station.key)}&model=${encodeURIComponent(model)}`,
  });
}
