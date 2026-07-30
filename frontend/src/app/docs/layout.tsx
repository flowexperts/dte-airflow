import Link from "next/link";
import { buildTree, type DocTreeNode } from "@/lib/docs";
import "./docs.css";

export const dynamic = "force-static";

export default async function DocsLayout({ children }: LayoutProps<"/docs">) {
  const tree = await buildTree();
  return (
    <div className="docs-shell">
      <aside className="docs-sidebar">
        <Link href="/docs" className="docs-brand">
          <span className="docs-brand-mark">dt·e</span>
          <span className="docs-brand-tag">docs</span>
        </Link>
        <nav>
          <TreeNav nodes={tree} />
        </nav>
        <div className="docs-back">
          <Link href="/">← Back to app</Link>
        </div>
      </aside>
      <main className="docs-main">{children}</main>
    </div>
  );
}

function TreeNav({ nodes, depth = 0 }: { nodes: DocTreeNode[]; depth?: number }) {
  return (
    <ul className={`docs-nav docs-nav-depth-${depth}`}>
      {nodes.map((n) => (
        <li key={(n.slug ?? [n.name]).join("/") || "_root"}>
          {n.slug !== null ? (
            <Link href={n.slug.length ? `/docs/${n.slug.join("/")}` : "/docs"}>{prettify(n.name)}</Link>
          ) : (
            <span className="docs-nav-section">{prettify(n.name)}</span>
          )}
          {n.children.length > 0 && <TreeNav nodes={n.children} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}

function prettify(s: string): string {
  if (s.includes(" ")) return s;
  return s.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
