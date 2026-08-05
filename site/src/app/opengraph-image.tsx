import { ImageResponse } from "next/og";
import { SITE_TITLE } from "@/lib/site";

export const dynamic = "force-static";
export const alt = SITE_TITLE;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
          background: "#0c0b09",
          backgroundImage:
            "radial-gradient(900px 600px at 82% 20%, rgba(232,68,26,0.25), transparent 65%)",
        }}
      >
        <div
          style={{
            display: "flex",
            fontSize: 96,
            fontWeight: 500,
            fontStyle: "italic",
            color: "#f2ede4",
            letterSpacing: -2,
          }}
        >
          dt<span style={{ color: "#e8441a" }}>e</span>
        </div>
        <div
          style={{
            display: "flex",
            marginTop: 28,
            fontSize: 44,
            fontWeight: 500,
            color: "#f2ede4",
          }}
        >
          Data Transformation Engine
        </div>
        <div
          style={{
            display: "flex",
            marginTop: 20,
            fontSize: 26,
            color: "#b8b0a4",
            maxWidth: 900,
          }}
        >
          Build data pipelines without burning tokens or developer time.
        </div>
      </div>
    ),
    { ...size },
  );
}
