import { randomBytes, randomUUID, createHash } from "node:crypto";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { getAuthenticatedGithubUser } from "@/lib/auth";
import {
  countRecentErrorReports,
  createStationErrorReport,
  hasDatabaseUrl,
  type StoredErrorReportAttachment,
} from "@/lib/postgres";
import { isSameOriginRequest, noindexJson } from "@/lib/request-security";
import { ERROR_REPORT_UPLOADS_DIR, toLogicalDataPath } from "@/lib/runtime-paths";
import { getSiteData } from "@/lib/site-data";
import { normalizeErrorReportCategory } from "@/lib/user-feedback";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_FILE_COUNT = 3;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL_BYTES = 16 * 1024 * 1024;
const MAX_DESCRIPTION_LENGTH = 2000;
const MAX_REPORTS_PER_STATION_PER_DAY = 5;
const MAX_REPORTS_PER_USER_PER_WEEK = 10;
const DAY_MS = 24 * 60 * 60 * 1000;
const WEEKLY_REPORT_LIMIT_WINDOW_MS = 7 * DAY_MS;

function detectImageType(bytes: Uint8Array): { mimeType: string; extension: string } | null {
  if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) {
    return { mimeType: "image/png", extension: "png" };
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return { mimeType: "image/jpeg", extension: "jpg" };
  }
  if (
    bytes.length >= 12 &&
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50
  ) {
    return { mimeType: "image/webp", extension: "webp" };
  }
  return null;
}

function safeFilename(value: string) {
  const name = path.basename(value || "screenshot").replace(/[^\w.-]+/g, "_").slice(0, 120);
  return name || "screenshot";
}

async function stationExists(stationKey: string) {
  const siteData = await getSiteData();
  return siteData.stations.some((station) => station.key === stationKey);
}

async function persistScreenshots(files: File[]): Promise<{ attachments: StoredErrorReportAttachment[]; paths: string[] }> {
  const now = new Date();
  const bucket = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
  const targetDir = path.join(ERROR_REPORT_UPLOADS_DIR, bucket);
  await mkdir(targetDir, { recursive: true });

  const attachments: StoredErrorReportAttachment[] = [];
  const paths: string[] = [];
  for (const file of files) {
    if (file.size <= 0) {
      continue;
    }
    if (file.size > MAX_FILE_BYTES) {
      throw new Error("FILE_TOO_LARGE");
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    const detected = detectImageType(bytes);
    if (!detected) {
      throw new Error("UNSUPPORTED_FILE_TYPE");
    }
    const storedFile = path.join(targetDir, `${randomUUID()}.${detected.extension}`);
    await writeFile(storedFile, bytes);
    paths.push(storedFile);
    attachments.push({
      originalFilename: safeFilename(file.name),
      storedPath: toLogicalDataPath(storedFile),
      mimeType: detected.mimeType,
      byteSize: bytes.byteLength,
      sha256: createHash("sha256").update(bytes).digest("hex"),
      accessToken: randomBytes(32).toString("hex"),
    });
  }
  return { attachments, paths };
}

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) {
    return noindexJson({ error: "Invalid request origin." }, { status: 403 });
  }
  if (!hasDatabaseUrl()) {
    return noindexJson({ error: "Database is not configured." }, { status: 503 });
  }
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (Number.isFinite(contentLength) && contentLength > MAX_TOTAL_BYTES) {
    return noindexJson({ error: "Upload is too large." }, { status: 413 });
  }
  const viewer = await getAuthenticatedGithubUser();
  if (!viewer) {
    return noindexJson({ error: "GitHub login is required." }, { status: 401 });
  }

  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return noindexJson({ error: "Invalid form data." }, { status: 400 });
  }

  const stationKey = String(formData.get("station") || "").trim();
  const category = normalizeErrorReportCategory(formData.get("category"));
  const description = String(formData.get("description") || "").trim().slice(0, MAX_DESCRIPTION_LENGTH);
  const currentUrl = String(formData.get("currentUrl") || "").trim().slice(0, 500) || null;
  const files = formData.getAll("screenshots").filter((item): item is File => item instanceof File && item.size > 0);

  if (!stationKey) {
    return noindexJson({ error: "Missing station." }, { status: 400 });
  }
  if (!(await stationExists(stationKey))) {
    return noindexJson({ error: "Station not found." }, { status: 404 });
  }
  if (!category) {
    return noindexJson({ error: "Invalid report category." }, { status: 400 });
  }
  if (description.length < 8) {
    return noindexJson({ error: "Description is too short." }, { status: 400 });
  }
  if (files.length > MAX_FILE_COUNT) {
    return noindexJson({ error: "Too many screenshots." }, { status: 400 });
  }

  const now = Date.now();
  const dailyRecent = await countRecentErrorReports({
    githubId: viewer.githubId,
    stationKey,
    since: new Date(now - DAY_MS),
  });
  if (dailyRecent.station >= MAX_REPORTS_PER_STATION_PER_DAY) {
    return noindexJson({ error: "该账号今天对这个站点的错误上报次数已达上限，请稍后再试。" }, { status: 429 });
  }
  const weeklyRecent = await countRecentErrorReports({
    githubId: viewer.githubId,
    stationKey,
    since: new Date(now - WEEKLY_REPORT_LIMIT_WINDOW_MS),
  });
  if (weeklyRecent.total >= MAX_REPORTS_PER_USER_PER_WEEK) {
    return noindexJson({ error: "该账号近 7 天错误上报次数已达上限，请下周再试。" }, { status: 429 });
  }

  let persisted: { attachments: StoredErrorReportAttachment[]; paths: string[] } = { attachments: [], paths: [] };
  try {
    persisted = await persistScreenshots(files);
    const result = await createStationErrorReport({
      stationKey,
      user: viewer,
      category,
      description,
      currentUrl,
      attachments: persisted.attachments,
    });
    return noindexJson({ ok: true, reportId: result.reportId });
  } catch (error) {
    await Promise.all(persisted.paths.map((filePath) => rm(filePath, { force: true })));
    if (error instanceof Error && error.message === "FILE_TOO_LARGE") {
      return noindexJson({ error: "Each screenshot must be 5MB or smaller." }, { status: 413 });
    }
    if (error instanceof Error && error.message === "UNSUPPORTED_FILE_TYPE") {
      return noindexJson({ error: "Only PNG, JPEG, and WebP screenshots are supported." }, { status: 400 });
    }
    return noindexJson({ error: "Failed to save report." }, { status: 500 });
  }
}
