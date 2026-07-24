# Mutation Testing

## What is mutation testing?

Mutation testing verifies that the test suite actually catches bugs. mutmut
makes small code changes ("mutants") — flipping `>` to `>=`, removing a `not`,
changing a constant — and then runs the tests. A mutant that causes no test
failure is a "survivor". Survivors reveal gaps where production code can be
changed without the tests noticing.

## Scope

mutmut is configured to mutate only `dte/compiler/` (see `[tool.mutmut]` in
`backend/pyproject.toml`). The compiler is the highest-value target because it
contains all step dispatch logic and ibis expression building. Other modules
(API routes, store layer) are excluded to keep run times practical.

## Running locally

From `backend/`:

```bash
# Full run against the compiler (takes several minutes)
cd backend
uv run mutmut run

# Limit parallelism if the machine is memory-constrained
uv run mutmut run --max-children 2

# View a summary after the run
uv run mutmut results

# Inspect a specific surviving mutant
uv run mutmut show <id>

# Apply a mutant to the source tree for manual inspection
uv run mutmut apply <id>
# Revert after inspection
uv run mutmut revert <id>
```

The `.mutmut-cache` file in `backend/` stores results between runs. Delete it
to force a clean sweep.

## CI

The `mutation.yml` workflow runs on every push to `main`. Survivors do **not**
currently fail the workflow (`|| true`) — the run is informational while a
baseline is being established.

Once a stable kill-rate is known, tighten by replacing `|| true` with a
threshold check (e.g. `uv run mutmut results | grep -c "Survived" | awk ...`).

## Acceptable survivors

Not every surviving mutant represents a test gap worth filling. Document
acceptable survivors here as they are identified:

- **Guard clauses that short-circuit to the same result**: e.g. mutating an
  early `return` in a path that is always followed by equivalent fallback logic.
- **Cosmetic string mutations** in error messages not asserted in tests: these
  should be killed only when the message text is part of the API contract.

Kill mutants where practical. Where a survivor is genuinely untestable or
the cost outweighs the benefit, add a comment in the source and record it here.
