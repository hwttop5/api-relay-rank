import { getOwnerAnnouncement } from "@/lib/owner-announcement";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const announcement = await getOwnerAnnouncement();

  return Response.json(announcement, {
    headers: {
      "cache-control": "no-store",
    },
  });
}
