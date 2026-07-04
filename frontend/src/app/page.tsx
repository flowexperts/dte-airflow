import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-lg w-full">
        <div className="flex items-baseline gap-2 mb-4">
          <span className="font-brand italic text-3xl leading-none">
            dt<em className="text-accent not-italic">e</em>
          </span>
          <span className="font-mono text-xs tracking-[0.18em] uppercase text-subtle border-l border-border pl-2">
            scaffold ok
          </span>
        </div>
        <h1 className="text-2xl font-medium mb-2">Design tokens wired.</h1>
        <p className="text-muted mb-6">
          Next.js 16 · Tailwind v4 · Outfit / Space Mono / Cormorant. Theme
          toggle persists to localStorage.
        </p>
        <div className="flex gap-2 items-center">
          <Link
            href="/preview"
            className="inline-flex items-center gap-2 px-3 py-2 bg-accent text-white text-sm font-medium rounded hover:bg-accent-h transition-colors"
          >
            Open /preview
          </Link>
          <ThemeToggle />
        </div>
      </div>
    </main>
  );
}
