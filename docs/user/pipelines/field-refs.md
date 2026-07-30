# Field names

Anywhere a step or destination asks you to name a column, these are the rules.

## Simple

Top-level column? Just its name.

```
customer_id
amount
```

## Nested

JSON files (and their S3, GCS, Azure equivalents) often have nested fields — an `order` object containing `amount`, a `user` containing `address` containing `city`. Reach into them with dots:

```
order.amount
user.address.city
```

The field picker in every step lets you drill down and click, so you rarely type these by hand.

## MongoDB and REST API — flat names

These sources flatten nested data using double underscores instead of dots:

```
address__city
```

Single token, no dots. Use it as-is.

## When the field picker is empty

You haven't inferred the schema on the source yet. Go to the source card, click **Infer schema**, come back. Every field picker in the builder fills in immediately.

## Result column names

When you write a nested field to the output, dte names the column after the **leaf** of the path (`order.amount` → `amount`). Rename it with an alias in the Select or Rename step, or in the destination's field list.
