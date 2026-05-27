import { readFile } from "node:fs/promises";

import { OWNER_ANNOUNCEMENT_MANIFEST_PATH } from "@/lib/runtime-paths";

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

function getString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getDisabledAnnouncement(sourceUrl = OWNER_ISSUE_URL): OwnerAnnouncement {
  return {
    title: "",
    updatedAt: "",
    content: "",
    sourceUrl,
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

export async function getOwnerAnnouncement(): Promise<OwnerAnnouncement> {
  try {
    const raw = await readFile(OWNER_ANNOUNCEMENT_MANIFEST_PATH, "utf8");
    return normalizeStoredAnnouncement(JSON.parse(raw));
  } catch {
    return getDisabledAnnouncement();
  }
}
