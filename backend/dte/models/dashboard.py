"""Dashboards — pipelines drawn instead of written (plan 064).

A dashboard is layout, not execution. Each tile names a pipeline and a chart
spec; the rows come from `GET /api/pipelines/{id}/preview`, which already
compiles and executes without touching a writer. There is no dashboard
execution path, no dashboard run, and no `/dashboards/{id}/data` endpoint —
a tile fetches its own pipeline's preview, which also gives every tile its
own loading and error state.

Its own module rather than another few hundred lines in `pipeline.py`, which
is past 1600 already.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator
from sqlalchemy import Column, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field as SMField
from sqlmodel import SQLModel

from dte.models.pipeline import _blank_id_means_generate

ChartKind = Literal["bar", "line", "area", "pie", "number", "table"]

# Kinds that draw a value series. `table` is the exception: it renders the
# pipeline's own columns, so demanding a `y` would be busywork for the one
# kind whose whole point is "show me what came back".
_NEEDS_Y = ("bar", "line", "area", "pie", "number")


class ChartSpec(BaseModel):
    """How to draw a tile's rows. Presentational only — never aggregates.

    Grouping and summing belong to the `aggregate` step, which the compiler
    already implements and the SQL panel already previews. A second
    aggregation living here would mean the Sample rows table and the tile
    could disagree about the same pipeline, with no way to tell which was
    right.
    """

    kind: ChartKind
    x: str | None = None
    y: list[str] = []
    # Group-by column: one line / colour per distinct value. Long-form rows
    # are pivoted to wide on the frontend (`chartData`), not here — the
    # backend never reshapes a preview response.
    series: str | None = None
    stacked: bool = False

    @model_validator(mode="after")
    def _check_fields_for_kind(self):
        if self.kind in _NEEDS_Y and not self.y:
            raise ValueError(f"chart kind {self.kind!r} needs at least one field in y")
        if self.kind == "number":
            if len(self.y) != 1:
                raise ValueError("chart kind 'number' takes exactly one field in y")
            # A single figure has no category axis. Dropping `x` beats
            # rejecting it: switching bar→number in the editor would
            # otherwise 422 on state the user can no longer see.
            object.__setattr__(self, "x", None)
            object.__setattr__(self, "series", None)
        return self


class DashboardTile(BaseModel):
    """One chart in the grid.

    `width` and `height` are enums, not pixels. Tiles flow in array order
    through a 12-column grid, so the only widths that tile cleanly are
    thirds, halves and full — a free integer would leave gaps no layout code
    can close, and free x/y would need collision handling to be usable.
    """

    _generate_blank_id = model_validator(mode="before")(
        classmethod(lambda cls, data: _blank_id_means_generate(data))
    )
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    title: str
    pipeline_id: str
    chart: ChartSpec
    width: Literal[4, 6, 12] = 6
    height: Literal["s", "m", "l"] = "m"
    # Rows this tile pulls. The preview endpoint takes a `limit` but caps
    # nothing, so the ceiling lives here: without it one tile can pull a
    # whole table into the browser and the page dies with no error.
    limit: int = SMField(default=1000, ge=1, le=10_000)


class DashboardBase(SQLModel):
    """API/domain fields. Routes bind POST/PUT bodies to this class."""

    _generate_blank_id = model_validator(mode="before")(
        classmethod(lambda cls, data: _blank_id_means_generate(data))
    )
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    name: str
    description: str | None = None
    tiles: list[DashboardTile] = SMField(default_factory=list)
    tenant_id: str = "default"

    @model_validator(mode="after")
    def _unique_tile_titles(self):
        titles = [t.title for t in self.tiles]
        dupes = sorted({t for t in titles if titles.count(t) > 1})
        if dupes:
            raise ValueError(f"duplicate tile titles: {', '.join(dupes)}")
        return self


class Dashboard(DashboardBase, table=True):
    __tablename__ = "dashboards"

    id: str = SMField(  # type: ignore[override]
        default_factory=lambda: str(_uuid.uuid4()), primary_key=True
    )
    name: str = SMField(sa_column=Column(Text, nullable=False))
    description: str | None = SMField(default=None, sa_column=Column(Text, nullable=True))
    tiles: list = SMField(  # type: ignore[override]
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )
    tenant_id: str = SMField(  # type: ignore[override]
        default="default", sa_column=Column(Text, nullable=False, server_default="default")
    )
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


DashboardCreate = DashboardBase
