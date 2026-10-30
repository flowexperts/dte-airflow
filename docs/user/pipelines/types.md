# Pipeline types

Pick the type when you create a pipeline. **Plugins ▸ DTE Pipelines** has a tab for each.

| Type | Reads | Writes | Use it to |
|---|---|---|---|
| [Transform](#transform) | Any source | One destination | Clean, reshape, join and load data |
| [Extract](#extract) | PDF documents | One destination | Turn documents into typed rows |
| [Quality Check](#quality-check) | Any source | Nothing | Assert rules about data, fail or warn |

## Transform

Sources → steps → one destination. Most pipelines are this.

![A transform pipeline: steps on the left, live preview on the right](../assets/pipelines/builder.png)

A run reports rows written, time taken and the steps it ran.

![A completed transform run](../assets/pipelines/run-detail.png)

Walkthrough: [Your first pipeline](../getting-started/02-first-pipeline.md).

## Extract

A Transform pipeline on a **Documents** source, a folder of PDFs. Two steps do the work:

1. **Extract text**: each PDF becomes text, one row per document or per page.
2. **Structure fields**: the text becomes the columns you declare (`invoice_number`, `vendor`, `total`), read by Claude or OpenAI through an Airflow connection, or by regex rules offline.

From there it's ordinary rows: filter, join and check them like any other table.

![Extract text and Structure fields steps for invoice PDFs](../assets/pipelines/extract-steps.png)

Parsed text and model answers are cached by content, so re-running or editing later steps doesn't pay twice. Needs the `unstructured` and `models` extras. Step details: [Documents (PDF)](../steps/index.md#documents-pdf).

## Quality Check

Sources → **Check** steps. No destination; it writes nothing.

Each check has a label, a condition (Basic rules or SQL) and what a failure means: **Fail** ends the run as `failed_quality`, **Warn** as `completed_with_warnings`.

![A check asserting every order has an amount and a known currency](../assets/pipelines/quality-steps.png)

The run lists each check, passed or failed.

![A quality run: all checks passed](../assets/pipelines/quality-run.png)

Point one at a Transform's destination table and schedule it after that pipeline to check every load.
