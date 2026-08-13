"""Turn a user-declared `DataModel` into a JSON Schema, and coerce what comes back.

The schema goes to the API's structured-outputs feature
(`output_config.format`), which constrains the response to valid JSON matching
it. That replaces the older prefill-and-hope pattern entirely — and prefill
returns a 400 on every current model anyway.

Structured outputs supports a **subset** of JSON Schema. Numeric and string
constraints (`minimum`, `maxLength`, `multipleOf`, …) are rejected, and every
object must carry `additionalProperties: false`. Emitting an unsupported
keyword 400s on the first real call, so this module deliberately generates the
narrow subset rather than passing through whatever the user typed.
"""

from __future__ import annotations

from typing import Any

from dte.providers.base import DataModel

# Declared field type → JSON Schema primitive. Dates travel as strings with a
# `format` hint: the model writes ISO-8601 text and `coerce_value` leaves it
# alone, because the eval comparators parse dates far more forgivingly than a
# schema validator would.
_JSON_TYPE: dict[str, str] = {
    "string": "string",
    "str": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "date": "string",
    "timestamp": "string",
}

_FORMAT_HINT = {"date": "date", "timestamp": "date-time"}


def json_schema_for(model: DataModel) -> dict[str, Any]:
    """Build the response schema for one document's extraction."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for spec in model.fields:
        json_type = _JSON_TYPE.get(spec.type, "string")
        # An optional field must be able to come back null. Without this the
        # model is forced to produce *something*, and an invented value is
        # worse than an honest absence.
        prop: dict[str, Any] = {
            "type": json_type if spec.required else [json_type, "null"]
        }
        if spec.description:
            prop["description"] = spec.description
        if spec.type in _FORMAT_HINT and spec.required:
            # `format` only applies to a bare string type; skip it on the
            # nullable union form, where it would be ambiguous.
            prop["format"] = _FORMAT_HINT[spec.type]
        properties[spec.name] = prop
        if spec.required:
            required.append(spec.name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def coerce_value(raw: Any, field_type: str) -> Any:
    """Coerce one returned value to the declared type.

    Never raises: a model returning garbage for one field costs that cell, not
    the run. Uncoercible values become None, which the eval scorer counts as a
    miss rather than silently passing a string through a numeric column.
    """
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None

    try:
        if field_type in ("float", "number"):
            return float(str(raw).replace(",", "").replace("$", "").strip())
        if field_type in ("int", "integer"):
            return int(float(str(raw).replace(",", "").strip()))
        if field_type in ("boolean", "bool"):
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("true", "yes", "1", "y")
    except (TypeError, ValueError):
        return None
    return raw


def coerce_row(values: dict[str, Any], model: DataModel) -> dict[str, Any]:
    """Coerce every declared field, filling absent keys with None so the
    output row has a stable shape regardless of what the provider returned."""
    return {
        spec.name: coerce_value(values.get(spec.name), spec.type)
        for spec in model.fields
    }
