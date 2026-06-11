import { revalidatePath } from "next/cache";

import { getAuthenticatedGithubUser } from "@/lib/auth";
import { hasDatabaseUrl, readStationReviewPage, upsertGithubUser, upsertStationReview } from "@/lib/postgres";
import { isSameOriginRequest, noindexJson } from "@/lib/request-security";
import { getSiteData } from "@/lib/site-data";
import { emptyReviewSummary, normalizeRating, normalizeReviewComment } from "@/lib/user-feedback";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function parsePagination(searchParams: URLSearchParams) {
  const limitValue = Number(searchParams.get("limit") || 10);
  const offsetValue = Number(searchParams.get("offset") || 0);
  return {
    limit: Number.isFinite(limitValue) ? Math.max(1, Math.min(30, Math.floor(limitValue))) : 10,
    offset: Number.isFinite(offsetValue) ? Math.max(0, Math.floor(offsetValue)) : 0,
  };
}

function emptyReviewPage(stationKey: string, viewer: Awaited<ReturnType<typeof getAuthenticatedGithubUser>>, limit = 10, offset = 0) {
  return {
    summary: emptyReviewSummary(stationKey),
    reviews: [],
    pagination: {
      limit,
      offset,
      nextOffset: null,
      hasMore: false,
    },
    viewer,
    viewerReview: null,
  };
}

async function stationExists(stationKey: string) {
  const siteData = await getSiteData();
  return siteData.stations.some((station) => station.key === stationKey);
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const stationKey = searchParams.get("station")?.trim() || "";
  const { limit, offset } = parsePagination(searchParams);
  if (!stationKey) {
    return noindexJson({ error: "Missing station." }, { status: 400 });
  }
  if (!(await stationExists(stationKey))) {
    return noindexJson({ error: "Station not found." }, { status: 404 });
  }

  const viewer = await getAuthenticatedGithubUser();
  if (!hasDatabaseUrl()) {
    return noindexJson(emptyReviewPage(stationKey, viewer, limit, offset));
  }

  try {
    const page = await readStationReviewPage(stationKey, viewer?.githubId, { limit, offset });
    return noindexJson({
      ...page,
      viewer,
    });
  } catch {
    return noindexJson(emptyReviewPage(stationKey, viewer, limit, offset));
  }
}

export async function POST(request: Request) {
  if (!isSameOriginRequest(request)) {
    return noindexJson({ error: "Invalid request origin." }, { status: 403 });
  }
  if (!hasDatabaseUrl()) {
    return noindexJson({ error: "Database is not configured." }, { status: 503 });
  }
  const viewer = await getAuthenticatedGithubUser();
  if (!viewer) {
    return noindexJson({ error: "GitHub login is required." }, { status: 401 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return noindexJson({ error: "Invalid JSON payload." }, { status: 400 });
  }
  const body = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const stationKey = String(body.station || "").trim();
  const rating = normalizeRating(body.rating);
  const comment = normalizeReviewComment(body.comment);

  if (!stationKey) {
    return noindexJson({ error: "Missing station." }, { status: 400 });
  }
  if (!(await stationExists(stationKey))) {
    return noindexJson({ error: "Station not found." }, { status: 404 });
  }
  if (rating === null) {
    return noindexJson({ error: "Rating must be one of 2, 4, 6, 8, 10." }, { status: 400 });
  }

  await upsertGithubUser(viewer);
  await upsertStationReview({ stationKey, user: viewer, rating, comment });
  revalidatePath(`/stations/${encodeURIComponent(stationKey)}`);
  revalidatePath("/ranking");
  revalidatePath("/");

  const page = await readStationReviewPage(stationKey, viewer.githubId, { limit: 10, offset: 0 });
  return noindexJson({
    ...page,
    viewer,
  });
}
