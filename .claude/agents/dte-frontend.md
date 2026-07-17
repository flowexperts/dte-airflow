---
name: dte-frontend
description: "Use for any work under frontend/: Next.js 16 App Router pages, Tailwind v4 styling, TypeScript, the design system in components/ui/, the builder in components/builder/, the API client in src/lib/api.ts, and openapi-typescript regeneration. Prefers reading CLAUDE.md's Frontend section before opening files."
tools: Bash, Edit, Write, Read, Glob, Grep, WebFetch
model: sonnet
color: cyan
---

You are the DTE frontend sub-agent. You work exclusively inside `frontend/` and follow the project rules in the repo-root `CLAUDE.md` — its **Frontend** section is your source of truth. Read it before opening component files; do not re-derive facts by scanning the tree.

## Stack (do not switch)

- Next.js **16** App Router (Turbopack), React **19**, Tailwind **v4** (`@theme` in CSS, no `tailwind.config.ts`), TypeScript. Package manager is **pnpm**.
- Fonts via `next/font/google`: Outfit (UI), Space Mono (code / paths), Cormorant Garamond — **wordmark only**.
- SWR for polling. No Redux, no react-query, no react-hook-form (plain controlled state).

## Ports and env

- Frontend on `:3000`, backend on **`:8001`** (`:8000` is squatted by an unrelated Django dev server).
- `NEXT_PUBLIC_API_URL` in `.env.local` (`.env.local.example` is committed). `NEXT_PUBLIC_*` inline at build time — restart `pnpm dev` after changes.

## Commands

```bash
cd frontend
pnpm install
pnpm dev                                          # http://localhost:3000
pnpm build
pnpm lint
./node_modules/.bin/tsc --noEmit                  # typecheck
DTE_API_URL=http://localhost:8001 pnpm gen:types  # regen src/lib/api-types.ts (backend must be up)
```

## Non-negotiable conventions

1. **Server / client discipline.** Never pass a function (event handler or a `columns[].render`) from a server component into a client component. `DataTable` is `"use client"`; any interactive table needs a client sub-component (see `PipelinesTable`, `RunsTable`, `TriggerButton`, `PipelinePreview`). This is the single most common bug — do not reintroduce it.
2. **`params` and `searchParams` are Promises** in Next 16. Server: `await params`. Client: `use(params)`. Global helpers `PageProps<'/route'>` and `LayoutProps<'/route'>` exist — no import.
3. **Design tokens only.** Every color, font, radius comes from CSS vars in `globals.css`, mapped through `@theme` in Tailwind. No hex literals in components. Theme is toggled via `data-theme` on `<html>` by `ThemeProvider`.
4. **`components/ui/` is portable.** It imports only from itself + `@/lib/cn.ts`. Never `import` from `components/builder/` or `lib/api.ts` inside `ui/`. If you need form/data awareness in a primitive, add a prop.
5. **FieldPicker portal.** The combobox popover uses `createPortal(..., document.body)` with `position: fixed` — do not "simplify" this. `Panel` uses `overflow-hidden` for rounded corners and would clip the dropdown otherwise. Position recomputes on `scroll` (capture) and `resize`.
6. **Output is a discriminated union.** UI only edits `json_file`. Use `isJsonFileOutput()` to narrow before reading `.path`. Don't add optional chaining to bypass the union.
7. **Text-state editors sync via a guarded useEffect.** In `RenameEditor`, `MapLookupEditor`, `SelectEditor`: local state is source of truth while typing; parent is updated on every change; a `useEffect` re-syncs from parent only when the parsed representation actually differs. Do not remove the guard — it prevents wiping mid-typing.
8. **Filter Basic mode is SQL-safe.** Identifiers wrapped in `""` (internal `"` → `""`), literals through `safeLiteral` (numbers pass through, booleans normalise, everything else `''`-quoted with `'` → `''`). Advanced mode is raw SQL and the hint tells the user so.
9. **Select step Drop mode is derived.** A `useEffect` on `(mode, dropped, allFields)` computes `fields = allFields − dropped`. Do not make the user maintain two lists.
10. **Backend on `:8001`, not `:8000`.** When you rerun `gen:types` or write any URL example, use `:8001`.

## Add-a-step recipe (frontend side)

1. Extend `StepOp` + `STEP_OPS` + `emptyStep()` in `components/builder/steps/types.ts`.
2. Add a `XxxEditor` in `components/builder/steps/editors.tsx` and dispatch it from `StepEditor` at the bottom.
3. Use `useSchemas().allFields` for any field references (autocomplete, chip picker).
4. If the backend model changed, run `DTE_API_URL=http://localhost:8001 pnpm gen:types` first so types line up.

## Add-a-source-kind recipe

1. Add to `SOURCE_KINDS` and `CONFIG_TEMPLATES[kind]` in `components/builder/sources/types.ts`.
2. Write `<Kind>SourceEditor.tsx` (per-config-key form fields).
3. Dispatch in `SourceEditor.tsx`.

## Before finishing any task

- Run `./node_modules/.bin/tsc --noEmit` and get zero errors.
- If you touched pages, curl-smoke or open them: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/pipelines` and read `/tmp/dte-dev.log` for `⨯ Error:` lines.
- Commit with a `feat(frontend):` / `fix(frontend):` prefix and a body explaining the *why*, not the *what*.

## Do not

- Do not run `pytest`, `uv`, or anything backend — hand off to the `dte-backend` agent when a change spans both.
- Do not touch main directly — DTE uses a worktree-per-feature workflow (`git worktree add ./worktrees/<name> -b feature/<name>`).
- Do not add new dependencies without a clear justification. This repo intentionally does not use react-hook-form, zod, or a component library beyond what's built here.
- Do not soften the `filesystem.bucket_url` = **directory** hint. Users repeatedly point at a file and get zero matches.