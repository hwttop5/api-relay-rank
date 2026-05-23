import { readFile } from "node:fs/promises";

import { resolveArchivedReportPath, resolveAuditRunReportPath } from "@/lib/audit-history";
import { getSiteData } from "@/lib/site-data";

const NOINDEX_HEADERS = {
  "X-Robots-Tag": "noindex",
};

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
    return new Response("Missing station or model query parameter.", { status: 400, headers: NOINDEX_HEADERS });
  }

  if (runId) {
    const body = await readReport(resolveAuditRunReportPath(stationKey, model, runId));
    if (!body) {
      return new Response("Audit report not found.", { status: 404, headers: NOINDEX_HEADERS });
    }
    return new Response(body, {
      headers: {
        "content-type": "text/markdown; charset=utf-8",
        "cache-control": "no-store",
        ...NOINDEX_HEADERS,
      },
    });
  }

  const siteData = await getSiteData();
  const station = siteData.stations.find((item) => item.key === stationKey);
  if (!station?.audits) {
    return new Response("Audit report not found.", { status: 404, headers: NOINDEX_HEADERS });
  }

  const summary = station.audits.latestByModel.find((item) => item.model === model);
  if (!summary?.reportPath) {
    return new Response("Audit report not found.", { status: 404, headers: NOINDEX_HEADERS });
  }

  const filePath = resolveArchivedReportPath(summary.reportPath);
  if (!filePath) {
    return new Response("Audit report path is invalid.", { status: 400, headers: NOINDEX_HEADERS });
  }

  const body = await readReport(filePath);
  if (!body) {
    return new Response("Audit report not found.", { status: 404, headers: NOINDEX_HEADERS });
  }

  return new Response(body, {
    headers: {
      "content-type": "text/markdown; charset=utf-8",
      "cache-control": "no-store",
      ...NOINDEX_HEADERS,
    },
  });
}
