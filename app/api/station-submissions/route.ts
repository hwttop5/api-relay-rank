import { randomBytes, randomUUID, createHash } from "node:crypto";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

import { getAuthenticatedGithubUser } from "@/lib/auth";
import {
  countRecentStationSubmissions,
  createStationSubmission,
  hasDatabaseUrl,
  type StoredStationSubmissionAttachment,
} from "@/lib/postgres";
import { isSameOriginRequest, noindexJson } from "@/lib/request-security";
import {
  maskTestApiKey,
  normalizeSubmissionAttachmentKind,
  normalizeSubmissionPaymentType,
  normalizeSubmissionPlatform,
} from "@/lib/station-submissions";
import type { StationSubmissionAttachmentKind } from "@/lib/types";
import { STATION_SUBMISSION_UPLOADS_DIR, toLogicalDataPath } from "@/lib/runtime-paths";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL_BYTES = 16 * 1024 * 1024;
const MAX_SCREENSHOTS_PER_KIND = 3;
const MAX_SUBMISSIONS_PER_URL_PER_DAY = 2;
const MAX_SUBMISSIONS_PER_USER_PER_WEEK = 8;
const DAY_MS = 24 * 60 * 60 * 1000;
const WEEKLY_SUBMISSION_LIMIT_WINDOW_MS = 7 * DAY_MS;
const SCHEMA_NOT_READY_MESSAGE = "申请收录数据表尚未初始化，请先完成数据库迁移后再提交。";

function isMissingDatabaseRelationError(error: unknown) {
  return Boolean(error && typeof error === "object" && (error as { code?: unknown }).code === "42P01");
}

function schemaNotReadyResponse() {
  return noindexJson({ error: SCHEMA_NOT_READY_MESSAGE }, { status: 503 });
}

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

function normalizeUrl(value: unknown): string {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  try {
    const parsed = new URL(text.startsWith("http") ? text : `https://${text}`);
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return "";
    }
    parsed.hash = "";
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return "";
  }
}

function normalizeEmail(value: unknown) {
  return String(value || "").trim().toLowerCase();
}

function limitedText(value: unknown, maxLength: number) {
  return String(value || "").trim().slice(0, maxLength);
}

async function persistScreenshot(
  kind: StationSubmissionAttachmentKind,
  file: File,
): Promise<{ attachment: StoredStationSubmissionAttachment; path: string }> {
  if (file.size <= 0) {
    throw new Error("MISSING_FILE");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("FILE_TOO_LARGE");
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  const detected = detectImageType(bytes);
  if (!detected) {
    throw new Error("UNSUPPORTED_FILE_TYPE");
  }
  const now = new Date();
  const bucket = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
  const targetDir = path.join(STATION_SUBMISSION_UPLOADS_DIR, bucket);
  await mkdir(targetDir, { recursive: true });
  const storedFile = path.join(targetDir, `${randomUUID()}.${detected.extension}`);
  await writeFile(storedFile, bytes);
  return {
    path: storedFile,
    attachment: {
      kind,
      originalFilename: safeFilename(file.name),
      storedPath: toLogicalDataPath(storedFile),
      mimeType: detected.mimeType,
      byteSize: bytes.byteLength,
      sha256: createHash("sha256").update(bytes).digest("hex"),
      accessToken: randomBytes(32).toString("hex"),
    },
  };
}

function getFiles(formData: FormData, field: string): File[] {
  return formData.getAll(field).filter((file): file is File => file instanceof File && file.size > 0);
}

async function handlePost(request: Request) {
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

  const stationName = limitedText(formData.get("stationName"), 120);
  const officialUrl = normalizeUrl(formData.get("officialUrl"));
  const paymentType = normalizeSubmissionPaymentType(formData.get("paymentType"));
  const platform = normalizeSubmissionPlatform(formData.get("platform"));
  const platformNote = limitedText(formData.get("platformNote"), 300) || null;
  const groupMultiplier = limitedText(formData.get("groupMultiplier"), 1000);
  const rechargeMultiplier = limitedText(formData.get("rechargeMultiplier"), 1000);
  const contactEmail = normalizeEmail(formData.get("contactEmail")).slice(0, 254);
  const testBaseUrl = normalizeUrl(formData.get("testBaseUrl"));
  const testApiKey = limitedText(formData.get("testApiKey"), 500);
  const notes = limitedText(formData.get("notes"), 1500);
  const currentUrl = limitedText(formData.get("currentUrl"), 500) || null;
  const groupKind = normalizeSubmissionAttachmentKind("group_multiplier");
  const rechargeKind = normalizeSubmissionAttachmentKind("recharge_multiplier");
  const groupScreenshots = getFiles(formData, "groupScreenshot");
  const rechargeScreenshots = getFiles(formData, "rechargeScreenshot");

  if (!stationName || stationName.length < 2) {
    return noindexJson({ error: "站点名称至少需要 2 个字符。" }, { status: 400 });
  }
  if (!officialUrl) {
    return noindexJson({ error: "请填写有效的官网地址。" }, { status: 400 });
  }
  if (!paymentType) {
    return noindexJson({ error: "请选择有效的付费类型。" }, { status: 400 });
  }
  if (!platform) {
    return noindexJson({ error: "请选择有效的平台判断。" }, { status: 400 });
  }
  if (platform === "other" && !platformNote) {
    return noindexJson({ error: "平台选择其他时，请填写平台说明。" }, { status: 400 });
  }
  if (groupMultiplier.length < 2) {
    return noindexJson({ error: "请填写分组倍率说明。" }, { status: 400 });
  }
  if (rechargeMultiplier.length < 2) {
    return noindexJson({ error: "请填写充值倍率说明。" }, { status: 400 });
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contactEmail)) {
    return noindexJson({ error: "请填写有效的联系邮箱。" }, { status: 400 });
  }
  if (!testBaseUrl) {
    return noindexJson({ error: "请填写有效的测试 BaseURL。" }, { status: 400 });
  }
  if (testApiKey.length < 8) {
    return noindexJson({ error: "测试 API Key 过短，请确认填写完整。" }, { status: 400 });
  }
  if (!groupScreenshots.length || !rechargeScreenshots.length || !groupKind || !rechargeKind) {
    return noindexJson({ error: "请上传分组倍率和充值倍率截图。" }, { status: 400 });
  }
  if (groupScreenshots.length > MAX_SCREENSHOTS_PER_KIND || rechargeScreenshots.length > MAX_SCREENSHOTS_PER_KIND) {
    return noindexJson({ error: `每个截图栏位最多上传 ${MAX_SCREENSHOTS_PER_KIND} 张。` }, { status: 400 });
  }

  const now = Date.now();
  let dailyRecent: Awaited<ReturnType<typeof countRecentStationSubmissions>>;
  let weeklyRecent: Awaited<ReturnType<typeof countRecentStationSubmissions>>;
  try {
    dailyRecent = await countRecentStationSubmissions({
      githubId: viewer.githubId,
      officialUrl,
      since: new Date(now - DAY_MS),
    });
    weeklyRecent = await countRecentStationSubmissions({
      githubId: viewer.githubId,
      officialUrl,
      since: new Date(now - WEEKLY_SUBMISSION_LIMIT_WINDOW_MS),
    });
  } catch (error) {
    if (isMissingDatabaseRelationError(error)) {
      return schemaNotReadyResponse();
    }
    throw error;
  }
  if (dailyRecent.url >= MAX_SUBMISSIONS_PER_URL_PER_DAY) {
    return noindexJson({ error: "该账号今天对这个官网的申请次数已达上限，请稍后再试。" }, { status: 429 });
  }
  if (weeklyRecent.total >= MAX_SUBMISSIONS_PER_USER_PER_WEEK) {
    return noindexJson({ error: "该账号近 7 天申请次数已达上限，请下周再试。" }, { status: 429 });
  }

  const persistedPaths: string[] = [];
  try {
    const attachments: StoredStationSubmissionAttachment[] = [];
    for (const screenshot of groupScreenshots) {
      const persisted = await persistScreenshot(groupKind, screenshot);
      persistedPaths.push(persisted.path);
      attachments.push(persisted.attachment);
    }
    for (const screenshot of rechargeScreenshots) {
      const persisted = await persistScreenshot(rechargeKind, screenshot);
      persistedPaths.push(persisted.path);
      attachments.push(persisted.attachment);
    }
    const result = await createStationSubmission({
      stationName,
      officialUrl,
      paymentType,
      platform,
      platformNote,
      groupMultiplier,
      rechargeMultiplier,
      contactEmail,
      testBaseUrl,
      testApiKey,
      notes,
      currentUrl,
      user: viewer,
      attachments,
    });
    return noindexJson({
      ok: true,
      submissionId: result.submissionId,
      maskedTestApiKey: maskTestApiKey(testApiKey),
    });
  } catch (error) {
    await Promise.all(persistedPaths.map((filePath) => rm(filePath, { force: true })));
    if (error instanceof Error && error.message === "FILE_TOO_LARGE") {
      return noindexJson({ error: "Each screenshot must be 5MB or smaller." }, { status: 413 });
    }
    if (error instanceof Error && error.message === "UNSUPPORTED_FILE_TYPE") {
      return noindexJson({ error: "Only PNG, JPEG, and WebP screenshots are supported." }, { status: 400 });
    }
    if (isMissingDatabaseRelationError(error)) {
      return schemaNotReadyResponse();
    }
    return noindexJson({ error: "Failed to save station submission." }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    return await handlePost(request);
  } catch (error) {
    if (isMissingDatabaseRelationError(error)) {
      return schemaNotReadyResponse();
    }
    return noindexJson({ error: "服务器暂时无法保存申请，请稍后再试。" }, { status: 500 });
  }
}
