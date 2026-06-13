import type { MetadataRoute } from "next";

import { absoluteUrl } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/"],
        disallow: ["/api/audit-report", "/api/station-audit", "/api/station-submissions", "/api/station-submission-attachments"],
      },
    ],
    sitemap: absoluteUrl("/sitemap.xml"),
  };
}
