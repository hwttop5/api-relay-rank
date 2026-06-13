import { ImageResponse } from "next/og";

import { DEFAULT_DESCRIPTION, SITE_IMAGE_HEIGHT, SITE_IMAGE_WIDTH, SITE_TITLE } from "@/lib/seo";

export const alt = SITE_TITLE;
export const size = {
  width: SITE_IMAGE_WIDTH,
  height: SITE_IMAGE_HEIGHT,
};
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          alignItems: "stretch",
          background: "#101820",
          color: "#eef4ef",
          display: "flex",
          flexDirection: "column",
          height: "100%",
          justifyContent: "space-between",
          padding: "72px",
          width: "100%",
        }}
      >
        <div
          style={{
            alignItems: "center",
            display: "flex",
            gap: "24px",
          }}
        >
          <div
            style={{
              alignItems: "center",
              background: "#080d13",
              border: "5px solid #20d3a2",
              borderRadius: "32px",
              display: "flex",
              height: "112px",
              justifyContent: "center",
              width: "112px",
            }}
          >
            <div
              style={{
                background: "#f0b95a",
                borderRadius: "999px",
                height: "24px",
                width: "24px",
              }}
            />
          </div>
          <div
            style={{
              color: "#7adfbc",
              display: "flex",
              fontSize: "30px",
              fontWeight: 700,
              letterSpacing: "0",
            }}
          >
            AI relay ranking
          </div>
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "28px",
          }}
        >
          <div
            style={{
              color: "#eef4ef",
              display: "flex",
              fontSize: "82px",
              fontWeight: 800,
              letterSpacing: "0",
              lineHeight: 1.08,
            }}
          >
            {SITE_TITLE}
          </div>
          <div
            style={{
              color: "#b9c8c2",
              display: "flex",
              fontSize: "34px",
              lineHeight: 1.45,
              maxWidth: "960px",
            }}
          >
            {DEFAULT_DESCRIPTION}
          </div>
        </div>

        <div
          style={{
            alignItems: "center",
            color: "#20d3a2",
            display: "flex",
            fontSize: "28px",
            fontWeight: 700,
            justifyContent: "space-between",
          }}
        >
          <span>apirank.ttop5.cc</span>
          <span>排名 · 倍率 · 安全审计</span>
        </div>
      </div>
    ),
    size,
  );
}
