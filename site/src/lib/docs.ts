import fs from "node:fs";
import path from "node:path";
import { Marked, type Tokens } from "marked";
import { REPO_URL } from "@/lib/site";

/** The user guide lives in the repo at docs/user and is rendered at build
 *  time (static export). Slug = path under docs/user without `.md`; the
 *  README is the index (""). Sidebar order is NAV; titles come from each
 *  file's `# heading`, so the Markdown stays the single source. */

const ROOT = path.join(process.cwd(), "..", "docs", "user");
const EXCLUDE = ["scripts/"]; // contributor tooling, not user docs

export const NAV: { section: string; slugs: string[] }[] = [
  {
    section: "Start",
    slugs: [
      "",
      "self-hosting/install-plugin",
      "self-hosting/install",
      "getting-started/02-first-pipeline",
      "getting-started/03-concepts",
    ],
  },
  {
    section: "Build",
    slugs: [
      "pipelines/building",
      "pipelines/types",
      "steps/index",
      "pipelines/field-refs",
      "pipelines/preview-and-run",
      "pipelines/scheduling",
      "pipelines/notifications",
      "pipelines/lookup-tables",
    ],
  },
  { section: "Connect", slugs: ["connections/index", "sources/index", "destinations/index"] },
  {
    section: "Operate",
    slugs: ["self-hosting/secrets", "self-hosting/scaling", "self-hosting/upgrading"],
  },
  { section: "Under the hood", slugs: ["architecture/overview", "architecture/data-flow"] },
  { section: "Help", slugs: ["troubleshooting", "faq"] },
];

export type Doc = { slug: string; title: string; description: string; html: string };

const fileFor = (slug: string) => path.join(ROOT, slug === "" ? "README.md" : `${slug}.md`);
export const hrefFor = (slug: string) => (slug ? `/docs/${slug}/` : "/docs/");

/** GitHub's heading-anchor rule, so `install-plugin.md#2-set-database_url` keeps working. */
const anchor = (text: string) =>
  text
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");

function render(slug: string, md: string): string {
  const dir = path.dirname(fileFor(slug));
  const marked = new Marked({
    renderer: {
      heading({ tokens, depth, text }: Tokens.Heading) {
        return `<h${depth} id="${anchor(text)}">${this.parser.parseInline(tokens)}</h${depth}>\n`;
      },
      link({ href, tokens }: Tokens.Link) {
        const label = this.parser.parseInline(tokens);
        const [, file, hash = ""] = href.match(/^([^:#?]+\.md)(#.*)?$/) ?? [];
        if (!file) {
          const ext = /^https?:/.test(href) ? ' rel="noopener"' : "";
          return `<a href="${href}"${ext}>${label}</a>`;
        }
        const target = path.resolve(dir, file);
        const rel = path.relative(ROOT, target);
        if (rel.startsWith("..")) {
          return `<a href="${REPO_URL}/blob/main/${path.relative(path.join(ROOT, "../.."), target)}">${label}</a>`;
        }
        if (!fs.existsSync(target))
          throw new Error(`docs/user/${slug || "README"}.md: broken link ${href}`);
        const to = rel === "README.md" ? "" : rel.replace(/\.md$/, "");
        return `<a href="${hrefFor(to)}${hash}">${label}</a>`;
      },
      // docs/user/assets/** is copied to public/docs/assets by `prebuild`.
      image({ href, text }: Tokens.Image) {
        const rel = path.relative(path.join(ROOT, "assets"), path.resolve(dir, href));
        if (rel.startsWith("..") || !fs.existsSync(path.join(ROOT, "assets", rel)))
          throw new Error(`docs/user/${slug || "README"}.md: image ${href} not in docs/user/assets`);
        return `<img src="/docs/assets/${rel}" alt="${text.replace(/"/g, "&quot;")}" loading="lazy">`;
      },
    },
  });
  return (marked.parse(md) as string)
    .replace(/<table>/g, '<div class="table-wrap"><table>')
    .replace(/<\/table>/g, "</table></div>");
}

export function getDoc(slug: string): Doc | undefined {
  const file = fileFor(slug);
  if (!fs.existsSync(file)) return undefined;
  const md = fs.readFileSync(file, "utf8");
  const title = md.match(/^# (.+)$/m)?.[1]?.trim() ?? slug;
  const para = md.split(/\n{2,}/).find((b) => b.trim() && !/^[#|`\-\d!<]/.test(b.trim())) ?? "";
  const description = para
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*`_]/g, "")
    .trim();
  return { slug, title, description, html: render(slug, md) };
}

const navSlugs = () => NAV.flatMap((s) => s.slugs);

/** Every doc slug. Throws at build time if NAV and docs/user disagree, so a
 *  new page can't ship unlinked and a renamed one can't 404 from the sidebar. */
export function allSlugs(): string[] {
  const onDisk = (fs.readdirSync(ROOT, { recursive: true }) as string[])
    .filter((f) => f.endsWith(".md") && !EXCLUDE.some((x) => f.startsWith(x)))
    .map((f) => (f === "README.md" ? "" : f.replace(/\.md$/, "")));
  const nav = navSlugs();
  const missing = onDisk.filter((s) => !nav.includes(s));
  const dangling = nav.filter((s) => !onDisk.includes(s));
  if (missing.length || dangling.length) {
    throw new Error(`docs NAV out of sync. Not in NAV: ${missing}. No such file: ${dangling}`);
  }
  return nav;
}

export const navTitles = () =>
  NAV.map(({ section, slugs }) => ({
    section,
    items: slugs.map((slug) => ({ slug, title: getDoc(slug)!.title })),
  }));
