import { readFile } from "node:fs/promises";
import path from "node:path";

import { hasDatabaseUrl, readStationSubmissionAttachmentByToken } from "@/lib/postgres";
import { resolveLogicalDataPath, STATION_SUBMISSION_UPLOADS_DIR } from "@/lib/runtime-paths";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const NOINDEX_HEADERS = {
  "X-Robots-Tag": "noindex",
};

function attachmentHeaders(filename: string, mimeType: string) {
  const encoded = encodeURIComponent(filename);
  return {
    ...NOINDEX_HEADERS,
    "content-type": mimeType,
    "cache-control": "private, no-store",
    "content-disposition": `inline; filename="${filename.replace(/"/g, "")}"; filename*=UTF-8''${encoded}`,
  };
}

export async function GET(_request: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!/^[a-f0-9]{64}$/.test(token) || !hasDatabaseUrl()) {
    return new Response("Not found.", { status: 404, headers: NOINDEX_HEADERS });
  }
  const attachment = await readStationSubmissionAttachmentByToken(token);
  if (!attachment) {
    return new Response("Not found.", { status: 404, headers: NOINDEX_HEADERS });
  }
  const filePath = resolveLogicalDataPath(attachment.storedPath);
  const uploadRoot = path.resolve(STATION_SUBMISSION_UPLOADS_DIR);
  const resolved = path.resolve(filePath);
  if (!resolved.startsWith(`${uploadRoot}${path.sep}`)) {
    return new Response("Invalid attachment path.", { status: 400, headers: NOINDEX_HEADERS });
  }
  let body: Buffer;
  try {
    body = await readFile(resolved);
  } catch {
    return new Response("Not found.", { status: 404, headers: NOINDEX_HEADERS });
  }
  return new Response(new Uint8Array(body), {
    headers: attachmentHeaders(attachment.originalFilename, attachment.mimeType),
  });
}
