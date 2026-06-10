import { revalidatePath } from "next/cache";

import { normalizePageViewPath } from "@/lib/page-view-path";
import { hasDatabaseUrl, recordPageViewEvent } from "@/lib/postgres";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function trackingEnabled() {
  return process.env.PAGE_VIEW_TRACKING_ENABLED !== "0";
}

export async function POST(request: Request) {
  if (!trackingEnabled() || !hasDatabaseUrl()) {
    return new Response(null, { status: 204 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return new Response(null, { status: 204 });
  }

  const path = payload && typeof payload === "object" ? (payload as { path?: unknown }).path : null;
  const normalized = normalizePageViewPath(path);
  if (!normalized) {
    return new Response(null, { status: 204 });
  }

  try {
    await recordPageViewEvent(normalized);
    revalidatePath(normalized.canonicalPath);
    if (normalized.canonicalPath === "/ranking") {
      revalidatePath("/");
    }
  } catch {
    return new Response(null, { status: 204 });
  }

  return new Response(null, { status: 204 });
}
