import { execFile, spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import readline from "node:readline";
import { promisify } from "node:util";
import { revalidatePath } from "next/cache";

import { AuditTargetError, assertPublicAuditTarget, seedRuntimeDataFromRepo, tryAcquireLock, withExclusiveLock } from "@/lib/audit-runtime";
import { getSiteData } from "@/lib/site-data";
import type { SiteData, StationAuditHistoryItem, StationAuditSummary } from "@/lib/types";

const execFileAsync = promisify(execFile);
const APP_ROOT = process.cwd();
const AUDIT_TIMEOUT_MS = 1000 * 60 * 20;
const MAX_AUDIT_REQUEST_BYTES = 16 * 1024;

export const runtime = "nodejs";

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
    env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", ...env },
    maxBuffer: 1024 * 1024 * 8,
    timeout: AUDIT_TIMEOUT_MS,
  });
}

function postgresSiteDataEnabled() {
  return process.env.SITE_DATA_SOURCE?.trim().toLowerCase() === "postgres" && Boolean(process.env.DATABASE_URL?.trim());
}

type AuditExecutedRow = { station: string; model: string; summary: string; report: string };
type AuditProgressPayload = Record<string, unknown> & { type?: unknown; message?: unknown; executed?: unknown };

function sanitizeEventValue(value: unknown, secrets: string[]): unknown {
  if (typeof value === "string") {
    return sanitizeAuditDetail(value, secrets);
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeEventValue(item, secrets));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, sanitizeEventValue(item, secrets)]));
  }
  return value;
}

function spawnPython(args: string[], env?: Record<string, string>): ChildProcessWithoutNullStreams {
  return spawn("python", args, {
    cwd: APP_ROOT,
    env: {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONUNBUFFERED: "1",
      PYTHONIOENCODING: "utf-8",
      ...env,
    },
  });
}

async function runPythonProgressJsonl(
  args: string[],
  env: Record<string, string>,
  secrets: string[],
  onEvent: (payload: AuditProgressPayload) => void,
) {
  const child = spawnPython(args, env);
  const stdout = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
  const stderr = readline.createInterface({ input: child.stderr, crlfDelay: Infinity });
  const executed: AuditExecutedRow[] = [];
  const stderrLines: string[] = [];

  const readStdout = (async () => {
    for await (const line of stdout) {
      const text = line.trim();
      if (!text) {
        continue;
      }
      try {
        const payload = JSON.parse(text) as AuditProgressPayload;
        if (payload.type === "result" && Array.isArray(payload.executed)) {
          executed.push(...(payload.executed as AuditExecutedRow[]));
          continue;
        }
        onEvent(sanitizeEventValue(payload, secrets) as AuditProgressPayload);
      } catch {
        onEvent({ type: "log", stream: "stdout", message: sanitizeAuditDetail(text, secrets) });
      }
    }
  })();

  const readStderr = (async () => {
    for await (const line of stderr) {
      const text = line.trim();
      if (!text) {
        continue;
      }
      stderrLines.push(text);
      onEvent({ type: "log", stream: "stderr", message: sanitizeAuditDetail(text, secrets) });
    }
  })();

  const exit = await new Promise<{ code: number | null; signal: NodeJS.Signals | null }>((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code, signal) => resolve({ code, signal }));
  });

  await Promise.allSettled([readStdout, readStderr]);
  if (exit.code !== 0) {
    const suffix = stderrLines.length > 0 ? ` ${stderrLines.join("\n")}` : "";
    throw new Error(`Audit engine failed with exit code ${exit.code ?? exit.signal ?? "unknown"}.${suffix}`);
  }

  return { executed };
}

function streamResponse(stream: ReadableStream<Uint8Array>) {
  return new Response(stream, {
    headers: {
      "cache-control": "no-store",
      "content-type": "application/x-ndjson; charset=utf-8",
      "x-accel-buffering": "no",
    },
  });
}

function auditRunIdFromReportPath(reportPath: string) {
  const parts = reportPath.replace(/\\/g, "/").split("/").filter(Boolean);
  const reportIndex = parts.lastIndexOf("report.md");
  return reportIndex > 0 ? parts[reportIndex - 1] : "";
}

export async function POST(request: Request) {
  await seedRuntimeDataFromRepo();

  let rawBody = "";
  try {
    rawBody = await request.text();
  } catch {
    return jsonResponse({ error: "Request body could not be read." }, 400);
  }

  if (Buffer.byteLength(rawBody, "utf8") > MAX_AUDIT_REQUEST_BYTES) {
    return jsonResponse({ error: "Request body exceeds 16 KiB." }, 413);
  }

  let payload: AuditRunPayload;
  try {
    payload = JSON.parse(rawBody) as AuditRunPayload;
  } catch {
    return jsonResponse({ error: "Request body must be valid JSON." }, 400);
  }

  const apiBaseUrl = typeof payload.apiBaseUrl === "string" ? payload.apiBaseUrl.trim() : "";
  const apiKey = typeof payload.apiKey === "string" ? payload.apiKey.trim() : "";
  const model = typeof payload.model === "string" ? payload.model.trim() : "";

  if (!apiBaseUrl || !apiKey || !model) {
    return jsonResponse({ error: "apiBaseUrl, apiKey and model are required." }, 400);
  }

  try {
    await assertPublicAuditTarget(apiBaseUrl);
  } catch (error) {
    const status = error instanceof AuditTargetError ? error.status : 403;
    return jsonResponse({ error: sanitizeAuditDetail(error) || "apiBaseUrl must target a public host." }, status);
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

  const auditLock = await tryAcquireLock("audit-run", 1000 * 60 * 60);
  if (!auditLock) {
    return jsonResponse({ error: "Another audit is already running." }, 429);
  }

  try {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        let closed = false;
        const send = (payload: AuditProgressPayload) => {
          if (closed) {
            return;
          }
          controller.enqueue(encoder.encode(`${JSON.stringify(sanitizeEventValue(payload, [apiKey]))}\n`));
        };
        const close = () => {
          if (!closed) {
            closed = true;
            controller.close();
          }
        };

        void (async () => {
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
              "--progress-jsonl",
            ];
            send({ type: "status", message: "已创建审计任务，正在启动审计流程。", station: stationKey, model });
            const { executed } = await runPythonProgressJsonl(script, { STATION_AUDIT_REQUEST_KEY: apiKey }, [apiKey], send);
            if (!executed[0]?.summary) {
              throw new Error("Audit completed without a summary path.");
            }

            send({ type: "status", message: "审计报告已归档，正在重建站点数据。", station: stationKey, model });
            try {
              await withExclusiveLock(
                "site-data-rebuild",
                async () => {
                  await runPythonJson(["scripts/build_site_data.py"]);
                  if (postgresSiteDataEnabled()) {
                    await runPythonJson(["scripts/publish_site_data_snapshot.py", "--source", "station-audit-run"]);
                    await runPythonJson(["scripts/publish_audit_history.py", "--delete-missing"]);
                  }
                },
                1000 * 60 * 60,
              );
            } catch (error) {
              if (error instanceof Error && error.message === "LOCK_HELD:site-data-rebuild") {
                throw new Error("Site data rebuild is already running. Retry later.");
              }
              throw error;
            }

            siteData = await getSiteData();

            revalidatePath("/");
            revalidatePath("/ranking");
            revalidatePath("/audit");
            revalidatePath("/statement");
            revalidatePath(`/stations/${encodeURIComponent(stationKey)}`);
            revalidatePath("/sitemap.xml");

            const station = siteData.stations.find((item) => item.key === stationKey);
            const summary = station?.audits?.latestByModel.find((item) => item.model === model) as StationAuditSummary | undefined;
            if (!station || !summary) {
              throw new Error("Audit summary was archived but not found in rebuilt site data.");
            }
            const runId = auditRunIdFromReportPath(summary.reportPath);
            if (!runId) {
              throw new Error("Audit summary was archived but its run id could not be resolved.");
            }

            const reportUrl = `/api/audit-report?station=${encodeURIComponent(station.key)}&model=${encodeURIComponent(model)}&run=${encodeURIComponent(runId)}`;
            const historyItem: StationAuditHistoryItem = {
              ...summary,
              stationKey: station.key,
              stationLabel: station.label,
              stationUrl: station.url || summary.auditedBaseUrl,
              runId,
              reportUrl,
            };

            send({
              type: "complete",
              message: "审计完成，结果已按站点归档。",
              result: {
                station: station.key,
                model,
                summary,
                historyItem,
                stationUrl: `/stations/${encodeURIComponent(station.key)}#audit`,
                reportUrl,
              },
            });
          } catch (error) {
            send({ type: "error", message: sanitizeAuditDetail(error, [apiKey]) || "Audit engine failed." });
          } finally {
            void auditLock.release();
            close();
          }
        })();
      },
    });

    return streamResponse(stream);
  } catch (error) {
    await auditLock.release();
    throw error;
  }
}
