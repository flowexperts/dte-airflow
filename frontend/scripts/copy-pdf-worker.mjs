/**
 * Copy the pdf.js worker into `public/` so it is served from our own origin.
 *
 * pdf.js runs parsing off the main thread and needs a URL it can hand to
 * `new Worker()`. The alternatives are worse: `new URL(..., import.meta.url)`
 * leans on bundler asset resolution that differs between Turbopack and
 * webpack, and a CDN URL is a cross-origin worker load that the CSP would
 * have to allow. A file in `public/` is just a file.
 *
 * Runs from `predev` / `prebuild`, so the copy tracks the installed version
 * automatically — a stale worker and a newer pdf.js fail with an opaque
 * "API version does not match Worker version".
 */
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const pkg = require.resolve("pdfjs-dist/package.json");
const src = join(dirname(pkg), "build", "pdf.worker.min.mjs");
const destDir = join(process.cwd(), "public", "pdfjs");

mkdirSync(destDir, { recursive: true });
copyFileSync(src, join(destDir, "pdf.worker.min.mjs"));

console.log(
  `pdf.js worker → public/pdfjs/pdf.worker.min.mjs (v${require("pdfjs-dist/package.json").version})`,
);
