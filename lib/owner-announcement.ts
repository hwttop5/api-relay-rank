import { readFile } from "node:fs/promises";

import { OWNER_ANNOUNCEMENT_MANIFEST_PATH, OWNER_ANNOUNCEMENT_STATUS_PATH } from "@/lib/runtime-paths";

const OWNER_ISSUE_URL = "https://github.com/hwttop5/github-actions/issues/1";

export interface OwnerAnnouncement {
  title: string;
  updatedAt: string;
  content: string;
  sourceUrl: string;
}

type StoredOwnerAnnouncement = Partial<OwnerAnnouncement> & {
  syncedAt?: unknown;
};

export interface OwnerAnnouncementStatus {
  ok: boolean;
  reason: string;
  lastAttemptAt: string;
  lastSuccessAt: string;
  updatedAt: string;
  sourceUrl: string;
  authMode: string;
  httpStatus: number | null;
  error: string;
  manifestPresent: boolean;
}

function getString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getBoolean(value: unknown) {
  return value === true;
}

function getNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getDisabledAnnouncement(sourceUrl = OWNER_ISSUE_URL): OwnerAnnouncement {
  return {
    title: "",
    updatedAt: "",
    content: "",
    sourceUrl,
  };
}

function getDefaultAnnouncementStatus(sourceUrl = OWNER_ISSUE_URL): OwnerAnnouncementStatus {
  return {
    ok: false,
    reason: "status_missing",
    lastAttemptAt: "",
    lastSuccessAt: "",
    updatedAt: "",
    sourceUrl,
    authMode: "",
    httpStatus: null,
    error: "",
    manifestPresent: false,
  };
}

function normalizeStoredAnnouncement(value: unknown): OwnerAnnouncement {
  if (!isRecord(value)) {
    return getDisabledAnnouncement();
  }

  const payload = value as StoredOwnerAnnouncement;
  const sourceUrl = getString(payload.sourceUrl) || OWNER_ISSUE_URL;
  const title = getString(payload.title);
  const updatedAt = getString(payload.updatedAt);
  const content = getString(payload.content);

  if (!title || !content) {
    return getDisabledAnnouncement(sourceUrl);
  }

  return {
    title,
    updatedAt,
    content,
    sourceUrl,
  };
}

function normalizeStoredAnnouncementStatus(value: unknown): OwnerAnnouncementStatus {
  if (!isRecord(value)) {
    return getDefaultAnnouncementStatus();
  }

  const sourceUrl = getString(value.sourceUrl) || OWNER_ISSUE_URL;
  return {
    ok: getBoolean(value.ok),
    reason: getString(value.reason),
    lastAttemptAt: getString(value.lastAttemptAt),
    lastSuccessAt: getString(value.lastSuccessAt),
    updatedAt: getString(value.updatedAt),
    sourceUrl,
    authMode: getString(value.authMode),
    httpStatus: getNumber(value.httpStatus),
    error: getString(value.error),
    manifestPresent: getBoolean(value.manifestPresent),
  };
}

export async function getOwnerAnnouncement(): Promise<OwnerAnnouncement> {
  try {
    const raw = await readFile(OWNER_ANNOUNCEMENT_MANIFEST_PATH, "utf8");
    return normalizeStoredAnnouncement(JSON.parse(raw));
  } catch {
    return getDisabledAnnouncement();
  }
}

export async function getOwnerAnnouncementStatus(): Promise<OwnerAnnouncementStatus> {
  try {
    const raw = await readFile(OWNER_ANNOUNCEMENT_STATUS_PATH, "utf8");
    return normalizeStoredAnnouncementStatus(JSON.parse(raw));
  } catch {
    return getDefaultAnnouncementStatus();
  }
}
