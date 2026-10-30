import type { NextConfig } from "next";
import path from "path";

const dev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  // Static export for Cloudflare Pages; `pnpm build` then writes the VitePress
  // docs into out/docs. In dev, /docs redirects to the VitePress dev server
  // that `pnpm dev` starts alongside Next. Redirect, not rewrite: proxying
  // Vite's dev server through Next breaks its CSS module requests.
  ...(dev
    ? {
        redirects: async () => [
          { source: "/docs/", destination: "http://localhost:3101/docs/", permanent: false },
          { source: "/docs/:path+", destination: "http://localhost:3101/docs/:path+", permanent: false },
        ],
      }
    : { output: "export" as const }),
  trailingSlash: true,
  images: { unoptimized: true },
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
