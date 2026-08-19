"""The comparison matrix is a property of the eval pipeline (plan 055).

A sweep already expands a matrix into one run per cell. The matrix itself
was transient — posted once to `POST /eval-sets/{id}/sweep` and never
stored — so a comparison could not be reopened, adjusted and re-run. You
started from an empty wizard and got a fresh set of variant pipelines every
time.

Storing it on the pipeline makes the comparison the thing you edit, and the
pipeline the thing that owns it.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from dte.models.pipeline import PipelineBase


STRUCTURE_STEP = {
    "op": "structure",
    "input_field": "content",
    "provider": "claude",
    "model": {"fields": [{"name": "total", "type": "float"}], "instructions": ""},
    "params": {"model": "claude-haiku-4-5"},
    "on_error": "null",
}


def _eval_pipeline(**over):
    body = {
        "id": "p1",
        "name": "p1",
        "pipeline_type": "eval",
        "sources": ["docs"],
        "steps": [STRUCTURE_STEP],
    }
    body.update(over)
    return PipelineBase(**body)


class TestMatrixIsStored:
    def test_absent_by_default(self):
        """No matrix means N=1 — an ordinary single-config eval run.

        That case is the nightly regression check ("did my prompt edit make
        this worse?") and has to stay first-class rather than becoming a
        degenerate comparison.
        """
        assert _eval_pipeline().matrix is None

    def test_round_trips_a_matrix(self):
        m = {"provider": ["claude", "regex"], "params.model": ["claude-haiku-4-5"]}
        assert _eval_pipeline(matrix=m).matrix == m


class TestMatrixIsRejectedWhereItWouldDoNothing:
    """A stored-and-ignored matrix is the silent no-op class this codebase
    keeps closing. Only eval pipelines sweep, so only they may carry one."""

    @pytest.mark.parametrize("ptype", ["transform", "quality"])
    def test_non_eval_pipeline_rejects_a_matrix(self, ptype):
        with pytest.raises(ValidationError) as e:
            _eval_pipeline(
                pipeline_type=ptype,
                output_id="out" if ptype == "transform" else None,
                matrix={"provider": ["claude"]},
            )
        assert "eval" in str(e.value).lower()

    def test_non_eval_pipeline_without_a_matrix_is_fine(self):
        assert PipelineBase(
            id="p1", name="p1", pipeline_type="transform", output_id="out"
        ).matrix is None


class TestAxesAreValidatedAtSave:
    """`apply_cell` refuses to create a leaf that does not exist, and that
    guard is what stops a typo becoming N identical cells reading as "this
    setting makes no difference". It used to fire only at spend — after an
    estimate had been quoted. Saving is the earlier, cheaper edge."""

    def test_unknown_axis_is_rejected(self):
        with pytest.raises(ValidationError) as e:
            _eval_pipeline(matrix={"provdier": ["claude"]})
        assert "provdier" in str(e.value)

    def test_known_creatable_axis_is_accepted(self):
        # params.model may not exist on the step yet; the twin normalises it,
        # and the sweep creates it. Save must not second-guess that.
        assert _eval_pipeline(matrix={"params.model": ["claude-opus-5"]}).matrix

    def test_empty_axis_list_is_rejected(self):
        """An axis with no values contributes nothing and silently drops the
        whole axis from the product — the user sees fewer cells than they
        configured, with no error."""
        with pytest.raises(ValidationError):
            _eval_pipeline(matrix={"provider": []})

    def test_matrix_must_be_lists(self):
        with pytest.raises(ValidationError):
            _eval_pipeline(matrix={"provider": "claude"})
