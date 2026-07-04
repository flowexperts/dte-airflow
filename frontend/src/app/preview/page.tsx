import { ThemeToggle } from "@/components/theme-toggle";

export default function Preview() {
  return (
    <main className="min-h-screen p-8">
      <header className="flex items-center justify-between mb-8 pb-4 border-b border-border">
        <div>
          <div className="font-mono text-[10px] tracking-[0.25em] uppercase text-subtle">
            /preview
          </div>
          <h1 className="text-2xl font-medium mt-1">Component gallery</h1>
        </div>
        <ThemeToggle />
      </header>

      <section className="mb-10">
        <h2 className="font-mono text-[10px] tracking-[0.2em] uppercase text-subtle mb-3">
          Coming next (Task 2)
        </h2>
        <ul className="grid grid-cols-2 md:grid-cols-3 gap-2 text-sm text-muted">
          {[
            "Button",
            "Pill",
            "NavItem",
            "Topbar",
            "PageHeader",
            "SectionHead",
            "DataTable",
            "StepRow",
            "Panel",
            "Item",
            "Metric",
            "MetricRow",
            "TimelineRow",
          ].map((n) => (
            <li
              key={n}
              className="border border-border rounded px-3 py-2 bg-surface"
            >
              {n}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="font-mono text-[10px] tracking-[0.2em] uppercase text-subtle mb-3">
          Palette
        </h2>
        <div className="grid grid-cols-4 md:grid-cols-6 gap-2">
          {[
            ["bg", "var(--bg)"],
            ["surface", "var(--surface)"],
            ["text", "var(--text)"],
            ["accent", "var(--accent)"],
            ["gold", "var(--gold)"],
            ["green", "var(--green)"],
          ].map(([name, val]) => (
            <div
              key={name}
              className="border border-border rounded aspect-square p-2 flex flex-col justify-between text-[10px] font-mono"
              style={{ background: val }}
            >
              <span
                className="uppercase tracking-[0.15em] font-bold"
                style={{ mixBlendMode: "difference", color: "#fff" }}
              >
                {name}
              </span>
              <span style={{ mixBlendMode: "difference", color: "#fff" }}>
                {val}
              </span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
