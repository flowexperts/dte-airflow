import fs from "node:fs/promises";
import path from "node:path";
import { marked } from "marked";

/**
 * Root of the user docs tree on disk.
 *
 * Order of resolution:
 *   1. DOCS_DIR env var (set to /docs/user in the docker-compose frontend service).
 *   2. `<repo>/docs/user` relative to the frontend cwd — works for `pnpm dev`
 *      and `next build` when the frontend is run outside docker.
 */
const DOCS_DIR = process.env.DOCS_DIR
  ? path.resolve(process.env.DOCS_DIR)
  : path.resolve(process.cwd(), "..", "docs", "user");

const IGNORED_DIRS = new Set(["assets", "scripts", "node_modules"]);

export interface DocEntry {
  /** URL slug segments, e.g. ["connections"] for docs/user/connections/index.md */
  slug: string[];
  /** File path relative to DOCS_DIR, e.g. "connections/index.md" */
  relPath: string;
  /** Human title, derived from the first H1 or the filename */
  title: string;
}

export interface DocTreeNode {
  name: string;              // segment or file title
  slug: string[] | null;     // null for section headers with no landing page
  children: DocTreeNode[];
}

async function walk(dir: string, rel = ""): Promise<DocEntry[]> {
  const out: DocEntry[] = [];
  let ents: import("node:fs").Dirent[];
  try {
    ents = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of ents) {
    if (ent.name.startsWith(".")) continue;
    if (IGNORED_DIRS.has(ent.name)) continue;
    const abs = path.join(dir, ent.name);
    const relNext = rel ? `${rel}/${ent.name}` : ent.name;
    if (ent.isDirectory()) {
      out.push(...(await walk(abs, relNext)));
    } else if (ent.isFile() && ent.name.endsWith(".md")) {
      const text = await fs.readFile(abs, "utf8");
      out.push({
        slug: fileToSlug(relNext),
        relPath: relNext,
        title: extractTitle(text, ent.name),
      });
    }
  }
  return out;
}

function fileToSlug(rel: string): string[] {
  // docs/user/README.md            → []
  // docs/user/connections/index.md → ["connections"]
  // docs/user/getting-started/01-sign-up.md → ["getting-started", "sign-up"]
  const noExt = rel.replace(/\.md$/, "");
  const parts = noExt.split("/").filter((p) => p && p.toLowerCase() !== "readme");
  if (parts[parts.length - 1] === "index") parts.pop();
  return parts.map((p) => p.replace(/^\d+-/, ""));
}

function extractTitle(md: string, fallback: string): string {
  const m = md.match(/^#\s+(.+?)\s*$/m);
  if (m && m[1]) return m[1].trim();
  return fallback.replace(/\.md$/, "").replace(/^\d+-/, "").replace(/-/g, " ");
}

export async function listDocs(): Promise<DocEntry[]> {
  return walk(DOCS_DIR);
}

export async function getDoc(slug: string[]): Promise<{ html: string; title: string; relPath: string } | null> {
  const entries = await listDocs();
  const target = entries.find(
    (e) => e.slug.length === slug.length && e.slug.every((s, i) => s === slug[i]),
  );
  if (!target) return null;
  const abs = path.join(DOCS_DIR, target.relPath);
  const src = await fs.readFile(abs, "utf8");
  const rewritten = rewriteLinks(src, target.relPath);
  const html = await marked.parse(rewritten, { async: true, gfm: true });
  return { html, title: target.title, relPath: target.relPath };
}

/**
 * Rewrite in-doc relative links so they resolve under /docs:
 *   [x](../steps/index.md)   from connections/index.md → /docs/steps
 *   [y](../assets/foo.png)   → /docs-assets/assets/foo.png (served by API route)
 * External links and anchors are left alone.
 */
function rewriteLinks(md: string, sourceRel: string): string {
  const sourceDir = path.posix.dirname(sourceRel);
  return md.replace(/\]\(([^)]+)\)/g, (full, href: string) => {
    if (/^(https?:|mailto:|#)/i.test(href)) return full;
    const [pathPart = "", hash] = href.split("#");
    const resolved = path.posix.normalize(path.posix.join(sourceDir, pathPart));
    // Assets and other non-md files leave the docs router — served via /docs-assets.
    if (!resolved.endsWith(".md")) {
      return `](/docs-assets/${resolved}${hash ? "#" + hash : ""})`;
    }
    const slug = fileToSlug(resolved);
    const target = slug.length ? `/docs/${slug.join("/")}` : "/docs";
    return `](${target}${hash ? "#" + hash : ""})`;
  });
}

/** Build a tree grouped by top-level section for the sidebar. */
export async function buildTree(): Promise<DocTreeNode[]> {
  const entries = await listDocs();
  const root: DocTreeNode = { name: "root", slug: null, children: [] };

  // Sort: root README first, then getting-started, then everything else alpha.
  const orderKey = (e: DocEntry) => {
    if (e.slug.length === 0) return "0";
    if (e.slug[0] === "getting-started") return "1_" + e.relPath;
    if (e.slug[0] === "connections") return "2_" + e.relPath;
    if (e.slug[0] === "sources") return "3_" + e.relPath;
    if (e.slug[0] === "destinations") return "4_" + e.relPath;
    if (e.slug[0] === "steps") return "5_" + e.relPath;
    if (e.slug[0] === "pipelines") return "6_" + e.relPath;
    if (e.slug[0] === "troubleshooting") return "7";
    if (e.slug[0] === "faq") return "8";
    if (e.slug[0] === "self-hosting") return "9_" + e.relPath;
    if (e.slug[0] === "architecture") return "A_" + e.relPath;
    return "Z_" + e.relPath;
  };
  entries.sort((a, b) => orderKey(a).localeCompare(orderKey(b)));

  for (const e of entries) {
    if (e.slug.length === 0) {
      root.children.push({ name: e.title, slug: [], children: [] });
      continue;
    }
    let cursor: DocTreeNode = root;
    for (let i = 0; i < e.slug.length; i++) {
      const seg = e.slug[i]!;
      const isLeaf = i === e.slug.length - 1;
      let node = cursor.children.find((c) => c.name === seg);
      if (!node) {
        node = { name: seg, slug: null, children: [] };
        cursor.children.push(node);
      }
      if (isLeaf) {
        node.slug = e.slug;
        node.name = e.title;
      }
      cursor = node;
    }
  }
  return root.children;
}

export async function readAssetBytes(rel: string): Promise<{ bytes: Buffer; mime: string } | null> {
  const safe = path.posix.normalize(rel);
  if (safe.startsWith("..") || safe.includes("\0")) return null;
  const abs = path.join(DOCS_DIR, safe);
  try {
    const bytes = await fs.readFile(abs);
    return { bytes, mime: mimeFor(safe) };
  } catch {
    return null;
  }
}

function mimeFor(rel: string): string {
  if (rel.endsWith(".png")) return "image/png";
  if (rel.endsWith(".jpg") || rel.endsWith(".jpeg")) return "image/jpeg";
  if (rel.endsWith(".svg")) return "image/svg+xml";
  if (rel.endsWith(".gif")) return "image/gif";
  if (rel.endsWith(".webp")) return "image/webp";
  return "application/octet-stream";
}
