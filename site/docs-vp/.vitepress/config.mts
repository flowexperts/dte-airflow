import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { defineConfig } from "vitepress";
import llmstxt from "vitepress-plugin-llms";

const vueDir = path.dirname(createRequire(import.meta.url).resolve("vue/package.json"));

// The user guide stays in docs/user (plain GitHub-readable Markdown); VitePress
// renders it at /docs/ and writes into Next's static export, so both ship as
// one Cloudflare Pages deploy. Sidebar order is ours; titles come from each
// file's `# heading`.
const page = (text: string, link: string) => ({ text, link });

const DOCS_URL = "https://dte.flowexperts.ai/docs/";
const SRC_DIR = path.resolve(__dirname, "../../../docs/user");

// No page carries a `description:` frontmatter, so derive one from the first
// prose paragraph; otherwise every page ships the same meta description.
function firstParagraph(file: string): string {
  const md = readFileSync(path.join(SRC_DIR, file), "utf8").replace(/^---[\s\S]*?---/, "");
  const para = md
    .split(/\n\s*\n/)
    .map((b) => b.trim())
    .find((b) => b && !/^(#|```|\||>|<|!\[|[-*] |\d+\. )/.test(b));
  if (!para) return "";
  const plain = para
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[`*_]/g, "")
    .replace(/\s+/g, " ");
  return plain.length > 160 ? `${plain.slice(0, 157).replace(/\s\S*$/, "")}…` : plain;
}

const pageUrl = (relativePath: string) =>
  DOCS_URL + relativePath.replace(/(^|\/)index\.md$/, "$1").replace(/\.md$/, "");

export default defineConfig({
  title: "DTE Docs",
  description: "User guide for DTE, the visual pipeline builder for Apache Airflow.",
  base: "/docs/",
  srcDir: "../../docs/user",
  srcExclude: ["scripts/**"],
  outDir: "../out/docs",
  cleanUrls: true,
  ignoreDeadLinks: "localhostLinks",
  rewrites: { "README.md": "index.md" },
  sitemap: { hostname: DOCS_URL },
  transformPageData(pageData) {
    pageData.description = pageData.frontmatter.description || firstParagraph(pageData.filePath) || pageData.description;
  },
  transformHead({ pageData, title, description }) {
    const url = pageUrl(pageData.relativePath);
    return [
      ["link", { rel: "canonical", href: url }],
      ["meta", { property: "og:type", content: "article" }],
      ["meta", { property: "og:site_name", content: "DTE Docs" }],
      ["meta", { property: "og:url", content: url }],
      ["meta", { property: "og:title", content: title }],
      ["meta", { property: "og:description", content: description }],
      ["meta", { property: "og:image", content: "https://dte.flowexperts.ai/opengraph-image" }],
      ["meta", { name: "twitter:card", content: "summary_large_image" }],
    ];
  },
  head: [
    ["link", { rel: "preconnect", href: "https://fonts.googleapis.com" }],
    ["link", { rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@1,500&family=Bricolage+Grotesque:opsz,wght@12..96,400..800&family=Geist+Mono:wght@400;700&display=swap" }],
  ],
  // The Markdown lives outside site/, so Vue must resolve from here, not from docs/user.
  // Writes /docs/llms.txt, /docs/llms-full.txt and a .md twin of every page.
  vite: { plugins: [llmstxt({ domain: "https://dte.flowexperts.ai" })], resolve: { alias: [{ find: /^vue($|\/)/, replacement: `${vueDir}$1` }] } },
  markdown: {
    // `{{ dte_message }}` in inline code is literal text, not a Vue binding.
    config(md) {
      const inline = md.renderer.rules.code_inline!;
      md.renderer.rules.code_inline = (...args) => inline(...args).replace("<code", "<code v-pre");
    },
  },
  themeConfig: {
    siteTitle: 'dt<span class="e">e</span> <small>docs</small>',
    nav: [
      { text: "Use cases", link: "https://dte.flowexperts.ai/use-cases/", target: "_self" },
      { text: "Integrations", link: "https://dte.flowexperts.ai/integrations/", target: "_self" },
    ],
    socialLinks: [{ icon: "github", link: "https://github.com/flowexperts/dte-airflow" }],
    search: { provider: "local" },
    outline: { level: [2, 3], label: "On this page" },
    editLink: { pattern: "https://github.com/flowexperts/dte-airflow/edit/main/docs/user/:path", text: "Edit this page on GitHub" },
    footer: { message: "Built and maintained by flowexperts.ai. Apache-2.0.", copyright: "Apache Airflow is a trademark of the ASF. DTE is not affiliated with or endorsed by the ASF." },
    sidebar: [
      { text: "Start", items: [page("Overview", "/"), page("Install into your own Airflow", "/self-hosting/install-plugin"), page("Try it with Docker Compose", "/self-hosting/install"), page("Your first pipeline", "/getting-started/02-first-pipeline"), page("Core ideas", "/getting-started/03-concepts")] },
      { text: "Build", items: [page("Building a pipeline", "/pipelines/building"), page("Pipeline types", "/pipelines/types"), page("Steps", "/steps/"), page("Field names", "/pipelines/field-refs"), page("Preview & run", "/pipelines/preview-and-run"), page("Scheduling", "/pipelines/scheduling"), page("Notifications", "/pipelines/notifications"), page("Lookup tables", "/pipelines/lookup-tables")] },
      { text: "Connect", items: [page("Connections", "/connections/"), page("Sources", "/sources/"), page("Destinations", "/destinations/")] },
      { text: "Operate", items: [page("Secrets & environment", "/self-hosting/secrets"), page("Scaling and execution", "/self-hosting/scaling"), page("Upgrading", "/self-hosting/upgrading")] },
      { text: "Under the hood", items: [page("Architecture overview", "/architecture/overview"), page("Data flow", "/architecture/data-flow")] },
      { text: "Help", items: [page("Troubleshooting", "/troubleshooting"), page("FAQ", "/faq")] },
    ],
  },
});
