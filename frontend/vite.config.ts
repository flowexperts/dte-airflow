import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Airflow `react_apps` bundle (plan 066). Airflow import()s this file and
// renders `globalThis.AirflowPlugin` inside its own layout, handing us its
// React, ReactDOM and router on globalThis — so they must not be bundled:
// a second React copy breaks every hook.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "dist",
    lib: {
      entry: "src/plugin.tsx",
      name: "AirflowPlugin",
      formats: ["umd"],
      fileName: () => "dte.umd.js",
    },
    rollupOptions: {
      external: ["react", "react-dom", "react/jsx-runtime", "react-router-dom"],
      output: {
        exports: "default",
        // Bundled CJS deps (use-sync-external-store, via swr + recharts) keep
        // a literal `require("react")` that `globals` does not rewrite; there
        // is no `require` in a browser, so resolve externals to the globals.
        intro: `var require = (m) => ({ react: globalThis.React, "react-dom": globalThis.ReactDOM, "react/jsx-runtime": globalThis.ReactJSXRuntime, "react-router-dom": globalThis.ReactRouterDOM })[m];`,
        globals: {
          react: "React",
          "react-dom": "ReactDOM",
          "react/jsx-runtime": "ReactJSXRuntime",
          "react-router-dom": "ReactRouterDOM",
        },
      },
    },
  },
});
