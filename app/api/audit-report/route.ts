import { readFile } from "node:fs/promises";
import path from "node:path";

import { getSiteData } from "@/lib/site-data";

const APP_ROOT = process.cwd();
const AUDIT_RUNS_ROOT = path.join(APP_ROOT, "data", "_audit_runs");

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const stationKey = searchParams.get("station")?.trim();
  const model = searchParams.get("model")?.trim();

  if (!stationKey || !model) {
    return new Response("Missing station or model query parameter.", { status: 400 });
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

  const filePath = path.resolve(APP_ROOT, summary.reportPath);
  if (!filePath.startsWith(path.resolve(AUDIT_RUNS_ROOT) + path.sep)) {
    return new Response("Audit report path is invalid.", { status: 400 });
  }

  let body: string;
  try {
    body = await readFile(filePath, "utf8");
  } catch {
    return new Response("Audit report not found.", { status: 404 });
  }

  return new Response(body, {
    headers: {
      "content-type": "text/markdown; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
