import { getSiteData } from "@/lib/site-data";

export const runtime = "nodejs";

export async function GET() {
  try {
    const siteData = await getSiteData();
    return Response.json(
      {
        ok: true,
        generatedAt: siteData.generatedAt,
        siteDataReadable: true,
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
