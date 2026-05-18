import { readFile } from "node:fs/promises";
import path from "node:path";

import { AUDIT_RUNS_ROOT, resolveAuditRunReportPath } from "@/lib/audit-history";
import { getSiteData } from "@/lib/site-data";

const APP_ROOT = process.cwd();

function resolveArchivedReportPath(reportPath: string) {
  const auditRoot = path.resolve(AUDIT_RUNS_ROOT);
  const filePath = path.resolve(APP_ROOT, reportPath);
  if (!filePath.startsWith(auditRoot + path.sep)) {
    return null;
  }
  return filePath;
}

async function readReport(filePath: string | null) {
  if (!filePath) {
    return null;
  }
  try {
    return await readFile(filePath, "utf8");
  } catch {
    return null;
  }
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const stationKey = searchParams.get("station")?.trim();
  const model = searchParams.get("model")?.trim();
  const runId = searchParams.get("run")?.trim();

  if (!stationKey || !model) {
    return new Response("Missing station or model query parameter.", { status: 400 });
  }

  if (runId) {
    const body = await readReport(resolveAuditRunReportPath(stationKey, model, runId));
    if (!body) {
      return new Response("Audit report not found.", { status: 404 });
    }
    return new Response(body, {
      headers: {
        "content-type": "text/markdown; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  }

  const siteData = await getSiteData();
  const station = siteData.stations.find((item) => item.key === stationKey);
  if (!station?.audits) {
    return new Response("Audit report not found.", { status: 404 });
  }

  const summary = station.audits.latestByModel.find((item) => item.model === model);
  if (!summary?.reportPath) {
    return new Response("Audit report not found.", { status: 404 });
  }

  const filePath = resolveArchivedReportPath(summary.reportPath);
  if (!filePath) {
    return new Response("Audit report path is invalid.", { status: 400 });
  }

  const body = await readReport(filePath);
  if (!body) {
    return new Response("Audit report not found.", { status: 404 });
  }

  return new Response(body, {
    headers: {
      "content-type": "text/markdown; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
