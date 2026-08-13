"""Structure providers: extracted text in, the user's declared columns out.

Three providers, deliberately different in kind:

- **regex** — fully deterministic, free, offline. Provenance is exact (the
  match span). The escape hatch for fields that don't need a model, and the
  only structure provider that can run in CI.
- **claude** / **openai** — model-backed, for the fields where pattern
  matching cannot work.

Every provider returns provenance or an explicit None. A wrong highlight is
worse than no highlight, so nothing here invents a span it didn't find.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from dte.providers.base import Block, DataModel, StructureResult
from dte.providers.schema import coerce_row, json_schema_for

_MISSING_DEP = (
    "{lib} is not installed — install the optional extra with "
    '`pip install "dte[unstructured]"`'
)

# Default models. Both are the current flagship for their provider; callers
# override per step via `params["model"]`.
DEFAULT_CLAUDE_MODEL = "claude-opus-5"
DEFAULT_OPENAI_MODEL = "gpt-5"

_PROMPT = """\
Extract the requested fields from the document below.

Rules:
- Use only what the document states. Do not infer, calculate, or fill from
  general knowledge.
- If a field is not present in the document, return null for it. A null is
  correct; an invented value is not.
- Return numbers as plain numbers with no currency symbols or thousands
  separators. Return dates as ISO-8601 (YYYY-MM-DD).

{instructions}
DOCUMENT:
{text}
"""


def _joined(blocks: list[Block]) -> str:
    return "\n\n".join(b.text or "" for b in blocks)


def _page_for_offset(blocks: list[Block], offset: int) -> int | None:
    """Map a character offset in the joined text back to its source page."""
    cursor = 0
    for block in blocks:
        length = len(block.text or "")
        if cursor <= offset < cursor + length:
            return block.page
        cursor += length + 2          # the "\n\n" join
    return None


class RegexStructureProvider:
    """Deterministic extraction by declared pattern. Free, offline, exact
    provenance — and the only structure provider CI can run."""

    name = "regex"

    def structure(
        self, blocks: list[Block], model: DataModel, params: dict
    ) -> StructureResult:
        started = time.perf_counter()
        text = _joined(blocks)

        missing = [s.name for s in model.fields if not s.pattern]
        if missing:
            return StructureResult(
                values={s.name: None for s in model.fields},
                provenance={s.name: None for s in model.fields},
                provider=self.name,
                blocks_text=text,
                error=(
                    "the regex provider needs a `pattern` on every field; "
                    f"missing on: {', '.join(missing)}"
                ),
            )

        raw: dict[str, Any] = {}
        provenance: dict[str, dict | None] = {}
        for spec in model.fields:
            match = re.search(spec.pattern, text)
            if match is None:
                raw[spec.name] = None
                provenance[spec.name] = None
                continue
            # Group 1 when the pattern captures, else the whole match.
            group = 1 if match.groups() else 0
            raw[spec.name] = match.group(group)
            start, end = match.span(group)
            provenance[spec.name] = {
                "confidence": 1.0,          # a match is a match
                "page": _page_for_offset(blocks, start),
                "char_start": start,
                "char_end": end,
                "quote": match.group(group),
            }

        return StructureResult(
            values=coerce_row(raw, model),
            provenance=provenance,
            provider=self.name,
            blocks_text=text,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )


class _ModelStructureProvider:
    """Shared body for the model-backed providers.

    Both use their SDK's structured-output support so the response is
    constrained to the derived JSON Schema — no prefill, no
    parse-and-retry loop, no "output ONLY valid JSON" incantation.
    """

    name = ""
    _default_model = ""

    def _call(self, prompt: str, schema: dict, params: dict) -> tuple[dict, int, int]:
        raise NotImplementedError

    def structure(
        self, blocks: list[Block], model: DataModel, params: dict
    ) -> StructureResult:
        started = time.perf_counter()
        text = _joined(blocks)
        empty = {s.name: None for s in model.fields}

        def done(values, provenance, error=None, usage=(0, 0)) -> StructureResult:
            return StructureResult(
                values=values,
                provenance=provenance,
                provider=self.name,
                blocks_text=text,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=error,
                input_tokens=usage[0],
                output_tokens=usage[1],
            )

        if not text.strip():
            return done(empty, dict.fromkeys(empty), "no extracted text to structure")

        prompt = _PROMPT.format(
            instructions=(model.instructions + "\n") if model.instructions else "",
            text=text,
        )

        try:
            raw, in_tok, out_tok = self._call(prompt, json_schema_for(model), params)
        except ImportError:
            return done(empty, dict.fromkeys(empty), _MISSING_DEP.format(lib=self.name))
        except Exception as exc:  # noqa: BLE001 — one bad document is one bad row
            return done(empty, dict.fromkeys(empty), f"{self.name}: {exc}")

        values = coerce_row(raw, model)
        # Provenance by locating each returned value in the source text. The
        # model is not asked for spans: self-reported offsets are unreliable,
        # and a wrong highlight is worse than none. Values the model
        # paraphrased simply get no span, which is honest.
        provenance: dict[str, dict | None] = {}
        for spec in model.fields:
            provenance[spec.name] = _locate(text, blocks, raw.get(spec.name))

        return done(values, provenance, usage=(in_tok, out_tok))


def _locate(text: str, blocks: list[Block], value: Any) -> dict | None:
    if value is None or not str(value).strip():
        return None
    needle = str(value)
    start = text.find(needle)
    if start < 0:
        return None
    return {
        "confidence": None,          # the API exposes no per-field confidence
        "page": _page_for_offset(blocks, start),
        "char_start": start,
        "char_end": start + len(needle),
        "quote": needle,
    }


class ClaudeStructureProvider(_ModelStructureProvider):
    name = "claude"
    _default_model = DEFAULT_CLAUDE_MODEL

    def _call(self, prompt: str, schema: dict, params: dict):
        import anthropic

        client = anthropic.Anthropic(api_key=params.get("api_key") or None)
        response = client.messages.create(
            model=params.get("model", self._default_model),
            max_tokens=params.get("max_tokens", 4096),
            # Structured outputs constrains the response to the schema.
            # NOTE: `temperature` is rejected with a 400 on Claude Opus 5 and
            # Sonnet 5 — StructureStep validation blocks it at save time.
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("request was declined by safety classifiers")

        text = next((b.text for b in response.content if b.type == "text"), "")
        return (
            json.loads(text),
            response.usage.input_tokens,
            response.usage.output_tokens,
        )


class OpenAIStructureProvider(_ModelStructureProvider):
    name = "openai"
    _default_model = DEFAULT_OPENAI_MODEL

    def _call(self, prompt: str, schema: dict, params: dict):
        import openai

        client = openai.OpenAI(api_key=params.get("api_key") or None)
        response = client.chat.completions.create(
            model=params.get("model", self._default_model),
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "extraction", "strict": True, "schema": schema},
            },
        )
        usage = response.usage
        return (
            json.loads(response.choices[0].message.content or "{}"),
            getattr(usage, "prompt_tokens", 0),
            getattr(usage, "completion_tokens", 0),
        )
