import { getOwnerAnnouncement, getOwnerAnnouncementStatus } from "@/lib/owner-announcement";
import { getSiteData } from "@/lib/site-data";

export const runtime = "nodejs";

export async function GET() {
  try {
    const [siteData, ownerAnnouncement, ownerAnnouncementStatus] = await Promise.all([
      getSiteData(),
      getOwnerAnnouncement(),
      getOwnerAnnouncementStatus(),
    ]);
    const ownerAnnouncementContentPresent = Boolean(ownerAnnouncement.title && ownerAnnouncement.content);
    return Response.json(
      {
        ok: true,
        generatedAt: siteData.generatedAt,
        siteDataReadable: true,
        ownerAnnouncement: {
          manifestReadable: ownerAnnouncementContentPresent,
          contentPresent: ownerAnnouncementContentPresent,
          updatedAt: ownerAnnouncement.updatedAt || ownerAnnouncementStatus.updatedAt,
          lastAttemptAt: ownerAnnouncementStatus.lastAttemptAt,
          lastSuccessAt: ownerAnnouncementStatus.lastSuccessAt,
          lastError: ownerAnnouncementStatus.error,
          authMode: ownerAnnouncementStatus.authMode,
        },
      },
      {
        headers: {
          "cache-control": "no-store",
        },
      },
    );
  } catch (error) {
    return Response.json(
      {
        ok: false,
        generatedAt: null,
        siteDataReadable: false,
        ownerAnnouncement: null,
        error: error instanceof Error ? error.message : "Failed to read site data.",
      },
      {
        status: 503,
        headers: {
          "cache-control": "no-store",
        },
      },
    );
  }
}
