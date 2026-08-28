"""Dashboard / tile / chart-spec validation (plan 064).

The chart spec is presentational only. It names which columns to draw and
how — it never groups or sums. Aggregation is what the `aggregate` step
already does, and a second aggregation engine living in the chart layer
would drift from the compiler's semantics while being unpreviewable: the
Sample rows table would show one thing and the tile another.

So the validators here are all about *which fields a kind needs*, and the
failure they prevent is a tile that saves happily and then renders blank
because `y` names nothing.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from dte.models.dashboard import ChartSpec, Dashboard, DashboardBase, DashboardTile


def _tile(**over):
    body = {
        "title": "Revenue by region",
        "pipeline_id": "p1",
        "chart": {"kind": "bar", "x": "region", "y": ["revenue"]},
    }
    body.update(over)
    return DashboardTile(**body)


class TestChartSpec:
    def test_bar_needs_a_value_field(self):
        with pytest.raises(ValidationError, match="y"):
            ChartSpec(kind="bar", x="region", y=[])

    def test_table_needs_no_value_field(self):
        """A table kind draws whatever columns the pipeline returns, so
        requiring `y` would force busywork to express "show me the rows"."""
        assert ChartSpec(kind="table").y == []

    def test_number_takes_exactly_one_value_field(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ChartSpec(kind="number", y=["a", "b"])

    def test_number_ignores_x(self):
        """A single figure has no category axis. Silently dropping `x`
        beats rejecting it — switching kind bar→number in the editor
        would otherwise error on state the user cannot see."""
        assert ChartSpec(kind="number", x="region", y=["total"]).x is None

    def test_line_accepts_several_value_fields(self):
        assert len(ChartSpec(kind="line", x="day", y=["opened", "closed"]).y) == 2


class TestTile:
    def test_defaults_to_half_width(self):
        assert _tile().width == 6

    def test_rejects_an_arbitrary_width(self):
        """Widths are an enum, not free pixels: tiles flow in a 12-column
        grid, and a 7 would leave a gap no layout code can close."""
        with pytest.raises(ValidationError):
            _tile(width=7)

    def test_row_limit_is_capped(self):
        """A tile fetches through the preview endpoint, which has no upper
        bound of its own — an unbounded tile limit would let one chart pull
        a whole table into the browser."""
        with pytest.raises(ValidationError):
            _tile(limit=10_000_000)

    def test_gets_an_id_when_blank(self):
        assert _tile().id


class TestDashboard:
    def test_rejects_duplicate_tile_titles(self):
        """Two tiles named the same thing make the grid unreadable and any
        "which chart is broken?" message ambiguous."""
        with pytest.raises(ValidationError, match="duplicate"):
            DashboardBase(name="Ops", tiles=[_tile(), _tile()])

    def test_accepts_an_empty_dashboard(self):
        """A dashboard is created before it has tiles — the editor needs
        something to save against."""
        assert DashboardBase(name="Ops").tiles == []

    def test_table_class_round_trips_tiles(self):
        """The real path: the route binds `DashboardBase`, the store writes
        `Dashboard`. `table=True` skips validators, so the tiles arriving
        here are already plain dicts from `model_dump` — which is also what
        comes back out of JSONB."""
        base = DashboardBase(name="Ops", tiles=[_tile()])
        d = Dashboard(**base.model_dump())
        assert d.tiles[0]["chart"]["kind"] == "bar"
