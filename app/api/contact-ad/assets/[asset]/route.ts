import { readFile } from "node:fs/promises";
import path from "node:path";

import { OWNER_ANNOUNCEMENT_ASSETS_DIR } from "@/lib/runtime-paths";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
  ".avif": "image/avif",
  ".gif": "image/gif",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

function getContentType(assetName: string) {
  return CONTENT_TYPE_BY_EXTENSION[path.extname(assetName).toLowerCase()] || "application/octet-stream";
}

function isSafeAssetName(asset: string) {
  return Boolean(asset) && asset === path.posix.basename(asset) && !asset.includes("\\");
}

export async function GET(_request: Request, { params }: { params: Promise<{ asset: string }> }) {
  const { asset } = await params;

  if (!isSafeAssetName(asset)) {
    return new Response("Asset not found.", { status: 404 });
  }

  const filePath = path.join(OWNER_ANNOUNCEMENT_ASSETS_DIR, asset);
  try {
    const body = await readFile(filePath);
    return new Response(body, {
      headers: {
        "cache-control": "public, max-age=31536000, immutable",
        "content-type": getContentType(asset),
        "x-content-type-options": "nosniff",
      },
    });
  } catch {
    return new Response("Asset not found.", { status: 404 });
  }
}
