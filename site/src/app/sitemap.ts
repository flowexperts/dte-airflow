import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";
import { USE_CASES } from "@/lib/use-cases";

export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return [
    {
      url: `${SITE_URL}/`,
      lastModified,
      changeFrequency: "weekly",
      priority: 1,
    },
    ...["/use-cases/", "/integrations/", "/open-source/"].map((path) => ({
      url: `${SITE_URL}${path}`,
      lastModified,
      changeFrequency: "monthly" as const,
      priority: 0.8,
    })),
    ...USE_CASES.map((u) => ({
      url: `${SITE_URL}/use-cases/${u.slug}/`,
      lastModified,
      changeFrequency: "monthly" as const,
      priority: 0.8,
    })),
  ];
}
