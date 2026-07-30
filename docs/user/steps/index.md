# Steps

Steps are the things you do to your data. Nine of them. Each step reads the current data, changes it, hands it to the next step. Order matters.

## Every step

| Step | What it does | You fill in | Handy for |
| ---- | ------------ | ----------- | --------- |
| **Filter** | Keeps rows matching a condition | On the *Basic* tab: a field, an operator (`=`, `>`, `<`, `in`, `is null`…), a value | Dropping cancelled orders, keeping last-30-days rows |
| **Rename** | Renames columns | A list of `new name` ← `old name` | Cleaning up ugly source column names |
| **Retype** | Changes a column's type | Field, target type (`string`, `int`, `float`, `bool`, `date`, `timestamp`) | Turning a text price into a number |
| **Map · lookup** | Looks up a value in a small [lookup table](../pipelines/lookup-tables.md) | Field to look up, lookup table, output column | Country code → country name |
| **Map · expression** | Calculates a new column | Output name, expression (a small formula) | `amount * 1.1`, `upper(name)` |
| **Sort** | Orders the rows | Fields to sort by, ascending/descending | Newest first |
| **Aggregate** | Groups rows and summarises | Group-by fields, aggregations (sum, count, avg, min, max) | Total revenue per customer per month |
| **Join** | Combines two sources on a matching column | Left source, right source, join column, join type (`inner`, `left`, `right`, `outer`) | Enrich orders with customer details |
| **Pivot** | Turns rows into columns | Row field, column field, value field, aggregation | Monthly sales as one column per month |
| **Select** | Keeps or drops columns | List of fields; mode = **Keep** or **Drop** | Keeping only a handful of columns; hiding PII |

## Two tabs on Filter

- **Basic** — the safe one. Pick field, operator, value. dte handles the escaping.
- **Advanced** — for people comfortable writing raw SQL conditions. No escaping — you're on your own here. Use Basic unless you need something Basic can't express.

## Aggregate — date parts

When grouping by a date or timestamp field, you can extract a part instead of grouping by the exact value:

| Part | Example |
| ---- | ------- |
| `year` | 2026 |
| `quarter` | 2 |
| `month` | 7 |
| `week` | 30 |
| `day` | 29 |
| `date` | 2026-07-29 |
| `dow` (day of week) | 3 |
| `hour` | 14 |

## Join — where the result goes

Join is the one step that writes to a **named** result instead of the running dataset. You give it an **Output id**. Later steps then pick which source to read from — the join result is one of them. This is how multi-source pipelines work.

## Adding a step

**Add step** button in the builder → pick from the menu. Reorder with the ↑/↓ arrows. Remove with ✕.

After every change, click **Preview** to see the result on a small sample. That's your fastest debugging loop.
