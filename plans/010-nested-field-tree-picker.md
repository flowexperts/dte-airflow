# Plan 010 — Nested Field Tree Picker

## Problem

When a source has nested JSON (`{"order": {"amount": 100, "currency": "USD"}, "user": {"id": "u_1", "address": {"city": "NYC"}}}`), dlt flattens keys with a `__` separator, so the DuckDB columns come back as `order__amount`, `order__currency`, `user__id`, `user__address__city`. The frontend's `SchemaProvider` stores those names as-is and hands them to every `FieldPicker` / `FieldMultiSelect`. Users see:

```
order__amount   order__currency   user__id   user__address__city   _dlt_id   _dlt_load_id
```

For anything beyond one level of nesting this is unreadable. It also buries useful structure: a picker of eight `order__*` fields could collapse to one `order` group; the same for `user`, `user.address`, etc.

## Non-goals

- Changing the backend or the wire format. Steps still store field references as `order__amount` (or `order.amount` — the compiler's `_resolve_field()` accepts both). This plan is purely display + interaction on the frontend.
- Editing free-text SQL (`filter` Advanced tab, `map · expression`). Those stay raw.
- Auto-inferring which fields to group by. Grouping is purely by the `__` delimiter.

## Architecture

Two ideas layered:

1. **Display transform.** A pure helper converts `order__amount` ↔ `order.amount` (or a `["order", "amount"]` path) so display and wire form stay in sync. Introduce a `FieldRef` type and `toDisplay(name)` / `toPath(name)` utilities in `components/ui/field-tree.ts`.
2. **Tree picker component.** A new `FieldTreePicker` renders schema fields as a collapsible tree:

   ```
   ▾ order                            (2 fields)
       ▸ amount     float64
       ▸ currency   string
   ▾ user
       ▸ id         string
       ▾ address
           ▸ city   string
   ▸ _dlt_id        string
   ```

   - Click a leaf to select (single-value mode) or toggle inclusion (multi mode).
   - Click a branch label to open / close the group; the disclosure caret is aria-friendly.
   - Groups with **all** leaves selected show a filled state; partial selection shows an intermediate state.
   - Selected leaves render as chips in multi mode, showing the friendly display path (`order.amount`).
   - Search input at the top filters leaves by fuzzy substring match (matches on any segment) and auto-expands hit branches.

`FieldTreePicker` reuses `FieldPicker`'s popover portal so it escapes `Panel`'s `overflow-hidden`. Position + click-outside behaviour is identical. Keyboard navigation: ↑/↓ moves within visible items, ← collapses / → expands a branch, Enter selects, Esc closes.

`FieldPicker` and `FieldMultiSelect` grow a `variant?: "flat" | "tree"` prop (default `"flat"` for back-compat). When `"tree"`, they render `FieldTreePicker` internally. In v1 the builder passes `"tree"` in every schema-aware editor.

### Data shape

```ts
interface FieldNode {
  name: string;               // display segment, e.g. "amount"
  wire: string;               // full flat name, e.g. "order__amount"
  path: string[];             // ["order", "amount"]
  type?: string;              // "float64", "string" — leaves only
  children?: FieldNode[];     // present iff branch
}
```

Building the tree: iterate `allFields` (from `SchemaProvider`), split each `name` on `__`, build a trie, attach `type` on the last node.

### Reserved names

`_dlt_id` and `_dlt_load_id` remain top-level leaves (single `__` prefix doesn't group them). No filtering; user decides whether to drop them via a `select` step in Drop mode.

## UX details

- Root is a scrollable list; branch nodes have a left indent per depth (`depth * 12px`).
- Type badge lives to the right of leaf names, in `text-subtle` mono.
- The chip in `FieldMultiSelect`'s selected list shows `order.amount` (dot form) but stores the wire form (`order__amount`).
- If schema is empty, the tree renders a small inline hint ("Infer schema on the source to see fields.") — same copy pattern as today's chip picker.
- No drag reordering. Tree order matches insertion order from the schema response.

## Tasks

Each task is one worktree / branch / PR.

### Task 1 — Display transform utility
- Branch: `feature/frontend-field-tree-transform`
- New file: `frontend/src/components/ui/field-tree.ts` — types (`FieldNode`, `FieldRef`), pure helpers:
  - `buildTree(fields: {name; type?}[]): FieldNode[]`
  - `toDisplay(wire: string): string` — `order__amount` → `order.amount`
  - `toWire(display: string): string` — `order.amount` → `order__amount` (accepts either form, idempotent)
  - `findNode(tree: FieldNode[], wire: string): FieldNode | null`
- Vitest unit tests covering: flat fields, one-level nest, deep nest, `_dlt_*` reserved names, empty input.
- No React yet.

### Task 2 — `FieldTreePicker` component
- Branch: `feature/frontend-field-tree-picker`
- New file: `frontend/src/components/ui/field-tree-picker.tsx`
- Portal + fixed positioning identical to `FieldPicker`'s pattern.
- Modes: `single` (select one, close) and `multi` (toggle inclusion).
- Keyboard model spelled out above.
- Uses design tokens; no new CSS variables.
- Storybook-style demo added to `/preview` under a new "Field tree" section with a hand-built fixture (nested order + user + `_dlt_*`).

### Task 3 — Integrate into `FieldPicker` and `FieldMultiSelect`
- Branch: `feature/frontend-field-tree-wire`
- Add `variant?: "flat" | "tree"` prop to both. Default `"flat"`.
- When `tree`, delegate rendering to `FieldTreePicker`.
- `FieldMultiSelect` chip label uses `toDisplay(wire)` but internal state remains wire-form strings.

### Task 4 — Switch builder editors to `variant="tree"`
- Branch: `feature/frontend-builder-adopt-tree`
- Update every schema-aware editor to pass `variant="tree"`:
  - `RetypeEditor.field`
  - `MapLookupEditor.field`
  - `RenameEditor` (LHS field only)
  - `SortEditor.by` (`FieldMultiSelect`)
  - `AggregateEditor.group_by` (`FieldMultiSelect`) + `aggregations[i].field` (`FieldPicker`)
  - `JoinEditor.on`
  - `PivotEditor.index / columns / values`
  - `SelectEditor` (Keep and Drop chip pickers)
  - `FilterEditor` Basic mode field cell
- Verify each editor still emits wire form to the step config (`order__amount`, not `order.amount`).

### Task 5 — CLAUDE.md update
- Branch: `feature/frontend-tree-docs`
- Extend the **Frontend › Builder** section: add a short note that nested JSON is displayed as a tree with dot-form labels but stored on the step in wire form; point at `field-tree.ts` as the transform seam.

## Files created / changed

- `frontend/src/components/ui/field-tree.ts` — new
- `frontend/src/components/ui/field-tree-picker.tsx` — new
- `frontend/src/components/ui/field-picker.tsx` — accept `variant` prop
- `frontend/src/components/ui/field-multi.tsx` — accept `variant` prop; use `toDisplay` for chip labels
- `frontend/src/components/ui/index.ts` — export new types + `FieldTreePicker`
- `frontend/src/components/builder/steps/editors.tsx` — pass `variant="tree"` everywhere
- `frontend/src/app/(app)/preview/page.tsx` — new "Field tree" showcase section
- `CLAUDE.md` — short note under **Frontend › Builder**
- New Vitest config if not already present (Task 1 will decide) — otherwise reuse existing test tooling

## What does NOT change

- `dte/**` — backend unchanged. `/api/schema/infer` still returns flat `parent__child` names.
- Step wire format — the compiler still receives `order__amount` (or `order.amount`) exactly as before.
- Filter Advanced mode, MapExpression — free-text SQL doesn't get autocomplete.
- `Panel`, `SchemaProvider`, `useSchemas()` — unchanged.

## Verification

- `pnpm gen:types` still produces an identical `api-types.ts` (backend didn't change).
- On `/preview`, the new Field tree section shows a nested source and lets you select `user.address.city`; the emitted string is `user__address__city`.
- On `/pipelines/{id}/edit` with an inferred nested source: every field input renders the tree. Selecting a nested leaf and saving produces a step config with wire-form field references. Re-opening the pipeline shows the same leaves selected (chip labels in dot form).
- `./node_modules/.bin/tsc --noEmit` clean.
- Backend suite still green (should be — no backend changes).
