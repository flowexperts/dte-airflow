"use client";

import { useTheme } from "./theme-provider";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      className="font-mono text-[10px] tracking-[0.15em] uppercase px-2 py-1 border border-border text-muted hover:text-text hover:border-border-2 rounded transition-colors"
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
