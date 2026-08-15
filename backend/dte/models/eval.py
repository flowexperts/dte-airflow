"""Eval harness storage models (plan 051, phase 1).

Two entities, both following the two-class SQLModel pattern documented in
CLAUDE.md: `XxxBase` carries the API-strict Literals and the Pydantic
validators, `Xxx(XxxBase, table=True)` carries the column definitions and
overrides those Literals back to `str` (SQLModel 0.0.39 cannot map a Literal
to a SQLAlchemy column).

Two design decisions are load-bearing enough to state here rather than in the
plan:

**`doc_key` is `sha256(document bytes)` — the same key the plan-050 artifact
store uses.** Labels therefore survive file renames and directory moves, they
join directly against extraction output with no path matching, and a document
already in the artifact cache is already keyed correctly. Keying on a path
instead would produce a set that silently scores zero the day someone
reorganises a bucket.

**`field_specs` is the scorer's own data model.** The task definition (what to
extract) and the scoring definition (how to compare it) are the same thing; if
they live in two places they drift, and a set gets scored against a spec it
was never labeled for. `to_field_specs()` is the single conversion, and the
comparator type is validated at save time — a bad comparator must fail when
the set is created, not at the end of a paid sweep.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Literal

from pydantic import field_validator, model_validator
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SMField
from sqlmodel import SQLModel

from dte.evals.comparators import COMPARATOR_TYPES
from dte.evals.scoring import FieldSpec

LabelSource = Literal["human", "consensus", "imported", "judge"]
Split = Literal["train", "holdout"]

_SHA256_LEN = 64


def _blank_id_means_generate(values):
    """Mirror of the same helper in `models/pipeline.py`: a blank `id` from a
    form means "generate one". `default_factory` alone does not achieve this —
    it fires only when the key is *absent*, so `{"id": ""}` would otherwise be
    written as an empty primary key."""
    if isinstance(values, dict) and values.get("id") == "":
        values = {k: v for k, v in values.items() if k != "id"}
    return values


# ─── Eval sets ───────────────────────────────────────────────────────────


class EvalSetBase(SQLModel):
    """A labeled corpus for one extraction task."""

    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str
    source_id: str
    field_specs: list[dict] = SMField(default_factory=list)
    labels_version: int = 1
    tenant_id: str = "default"

    _blank_id = model_validator(mode="before")(_blank_id_means_generate)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()

    @field_validator("field_specs")
    @classmethod
    def _validate_field_specs(cls, v: list[dict]) -> list[dict]:
        if not v:
            raise ValueError("an eval set needs at least one field spec")
        seen: set[str] = set()
        for spec in v:
            name = (spec.get("name") or "").strip()
            if not name:
                raise ValueError("every field spec needs a name")
            if name in seen:
                raise ValueError(f"duplicate field spec: {name!r}")
            seen.add(name)
            ftype = spec.get("type")
            if ftype not in COMPARATOR_TYPES:
                raise ValueError(
                    f"unknown comparator type {ftype!r} for field {name!r} — "
                    f"expected one of {sorted(COMPARATOR_TYPES)}"
                )
        return v

    def to_field_specs(self) -> list[FieldSpec]:
        """The one conversion into the scorer's model. Extraction-only keys
        (`description`) are deliberately dropped — they describe the task to
        the model, not the comparison to the scorer."""
        return [
            FieldSpec(
                name=s["name"],
                type=s["type"],
                comparator=dict(s.get("comparator") or {}),
            )
            for s in self.field_specs
        ]


class EvalSet(EvalSetBase, table=True):
    __tablename__ = "eval_sets"

    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    name: str = SMField(sa_column=Column(Text, nullable=False))  # type: ignore[override]
    source_id: str = SMField(sa_column=Column(Text, nullable=False))  # type: ignore[override]
    field_specs: list = SMField(  # type: ignore[override]
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    labels_version: int = SMField(  # type: ignore[override]
        default=1, sa_column=Column(Integer, nullable=False, server_default="1")
    )
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        ),
    )


# ─── Eval examples ───────────────────────────────────────────────────────


class EvalExampleBase(SQLModel):
    """One labeled document.

    `label_source` is never collapsed. Knowing a label came from an LLM judge
    rather than a human is exactly what you need when the scores look
    suspiciously good, and it is unrecoverable once lost.
    """

    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    eval_set_id: str
    doc_key: str
    doc_ref: str | None = None
    labels: dict = SMField(default_factory=dict)
    label_source: LabelSource = "human"
    split: Split = "train"
    labels_version: int | None = None
    tenant_id: str = "default"

    _blank_id = model_validator(mode="before")(_blank_id_means_generate)

    @field_validator("doc_key")
    @classmethod
    def _doc_key_is_a_sha256(cls, v: str) -> str:
        """A path or filename here would join against nothing, and the set
        would score a permanent zero with no error anywhere."""
        key = (v or "").strip().lower()
        if len(key) != _SHA256_LEN or any(c not in "0123456789abcdef" for c in key):
            raise ValueError(
                "doc_key must be a sha256 hex digest of the document bytes "
                "(the artifact-store key), not a path or filename"
            )
        return key


class EvalExample(EvalExampleBase, table=True):
    __tablename__ = "eval_examples"

    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    eval_set_id: str = SMField(  # type: ignore[override]
        sa_column=Column(
            Text, ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False
        )
    )
    doc_key: str = SMField(sa_column=Column(Text, nullable=False))  # type: ignore[override]
    doc_ref: str | None = SMField(default=None, sa_column=Column(Text, nullable=True))  # type: ignore[override]
    labels: dict = SMField(  # type: ignore[override]
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    # Override: Literal → str for SQLAlchemy mapping (SQLModel 0.0.39 gotcha).
    label_source: str = SMField(  # type: ignore[override]
        default="human", sa_column=Column(Text, nullable=False, server_default="human")
    )
    split: str = SMField(  # type: ignore[override]
        default="train", sa_column=Column(Text, nullable=False, server_default="train")
    )
    labels_version: int | None = SMField(  # type: ignore[override]
        default=None, sa_column=Column(Integer, nullable=True)
    )
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        ),
    )
