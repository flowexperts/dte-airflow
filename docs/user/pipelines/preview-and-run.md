# Preview & run

Two feedback loops. Use them together.

## Preview

**Preview** on the pipeline page runs your recipe on a small sample and shows the result — a table above the run history.

- Always safe. Preview **reads** sources; it never writes to a destination.
- Sample size is capped (about 20 rows). Preview shows the *shape* of the output, not row totals.
- If a step is broken — a bad type cast, a missing field, an invalid filter — the panel goes red and shows what went wrong. Fix, preview again. This is the fastest way to debug in dte.

## Trigger

**Trigger** starts a real run. dte kicks it off in the background and takes you to the run page — you don't wait, you watch.

## The run page

The run page refreshes every couple of seconds until the run is done.

You see:

- **Status** — `pending` → `running` → `completed` or `failed`
- **Rows written**
- **Elapsed** — how long the run took
- **Started at**
- On failure: the error, in full

Once the status is `completed` or `failed`, the page stops refreshing.

## Peek at the output

For file destinations, the run page has an **Output** section that shows the first few rows of the written file. Quick spot-check without leaving the app.

## Run history

The pipeline page shows recent runs. **Runs** in the sidebar shows the full history across every pipeline.
