import type { NextConfig } from "next";
import path from "path";
import bundleAnalyzer from "@next/bundle-analyzer";

const withAnalyzer = bundleAnalyzer({ enabled: process.env.ANALYZE === "true" });

const nextConfig: NextConfig = {
  turbopack: {
    root: path.join(__dirname),
  },
  async redirects() {
    return [
      // `/evals` listed eval *sets* while "Eval" under Pipelines listed eval
      // *pipelines* — two different objects one letter apart. The route is
      // now /eval-sets, matching the model, the table and the API. Kept as a
      // permanent redirect so links and bookmarks to the old path still land
      // somewhere, including the deep ones (/evals/{id}).
      { source: "/evals", destination: "/eval-sets", permanent: true },
      { source: "/evals/:path*", destination: "/eval-sets/:path*", permanent: true },
    ];
  },
};

export default withAnalyzer(nextConfig);
