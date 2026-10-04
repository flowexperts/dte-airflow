from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from dte.models.eval import (
        EvalExample,
        EvalExampleBase,
        EvalSet,
        EvalSetBase,
    )
    from dte.models.dashboard import Dashboard, DashboardBase
    from dte.models.pipeline import (
        Connection,
        Destination,
        DestinationBase,
        LookupTable,
        LookupTableBase,
        Pipeline,
        PipelineRevision,
        PipelineRevisionBase,
        Source,
        SourceBase,
    )


@runtime_checkable
class PipelineStore(Protocol):
    async def get(self, id: str) -> "Pipeline | None": ...
    async def save(self, pipeline: "Pipeline") -> None: ...
    async def list(self, limit: int = 50, offset: int = 0) -> "list[Pipeline]": ...
    async def delete(self, id: str) -> bool: ...


@runtime_checkable
class RunStore(Protocol):
    """Read-only: runs are Airflow dag runs plus DTE's `run_results` row."""

    async def get(self, id: str) -> dict | None: ...
    async def list_for_pipeline(
        self, pipeline_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]: ...
    async def count_for_pipeline(self, pipeline_id: str) -> int: ...
    async def delete_for_pipeline(self, pipeline_id: str) -> int: ...
    async def list_for_eval_set(
        self, eval_set_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]: ...
    async def list_for_sweep(self, sweep_id: str, limit: int = 50) -> list[dict]: ...
    async def list_sweep_runs_for_root(
        self, root_pipeline_id: str, limit: int = 500
    ) -> list[dict]: ...
    async def get_quality(self, run_id: str) -> list: ...


@runtime_checkable
class PipelineRevisionStore(Protocol):
    """Append-only history of pipeline edits. `save` writes a new immutable
    row per call — no upsert. `latest_for_pipeline` returns the most-recent
    revision id (used to pin runs at trigger time)."""

    async def save(self, revision: "PipelineRevisionBase | PipelineRevision") -> None: ...
    async def get(self, id: str) -> "PipelineRevision | None": ...
    async def list_for_pipeline(
        self, pipeline_id: str, limit: int = 100, offset: int = 0
    ) -> "list[PipelineRevision]": ...
    async def count_for_pipeline(self, pipeline_id: str) -> int: ...
    async def latest_for_pipeline(self, pipeline_id: str) -> "PipelineRevision | None": ...


@runtime_checkable
class RunEventStore(Protocol):
    """Per-step events of a run, for the /api/runs/{id}/events Timeline."""

    async def list_for_run(self, run_id: str) -> list[dict]: ...


@runtime_checkable
class SourceStore(Protocol):
    async def get(self, id: str) -> "Source | None": ...
    async def save(self, source: "SourceBase | Source") -> None: ...
    async def list(self, limit: int = 50, offset: int = 0) -> "list[Source]": ...
    async def delete(self, id: str) -> bool: ...


@runtime_checkable
class DestinationStore(Protocol):
    async def get(self, id: str) -> "Destination | None": ...
    async def save(self, destination: "DestinationBase | Destination") -> None: ...
    async def list(self, limit: int = 50, offset: int = 0) -> "list[Destination]": ...
    async def delete(self, id: str) -> bool: ...


@runtime_checkable
class LookupTableStore(Protocol):
    async def get(self, id: str) -> "LookupTable | None": ...
    async def save(self, lookup: "LookupTableBase | LookupTable") -> None: ...
    async def list(self, limit: int = 50, offset: int = 0) -> "list[LookupTable]": ...
    async def delete(self, id: str) -> bool: ...


@runtime_checkable
class DashboardStore(Protocol):
    """Dashboards are layout only — no run, no trigger, no execute.

    A tile's rows come from the pipeline preview endpoint, so this store
    never touches the engine. Same four verbs as every other entity store.
    """

    async def get(self, id: str) -> "Dashboard | None": ...
    async def save(self, dashboard: "DashboardBase | Dashboard") -> None: ...
    async def list(self, limit: int = 50, offset: int = 0) -> "list[Dashboard]": ...
    async def delete(self, id: str) -> bool: ...


@runtime_checkable
class ConnectionStore(Protocol):
    """Read-only view of Airflow Connections (`dte.airflow.connections`).
    `get` returns the mapped `Connection` with its credentials; `list`
    returns them masked to `{}`."""

    async def get(self, id: str) -> "Connection | None": ...
    async def list(self, limit: int = 50, offset: int = 0) -> "list[Connection]": ...


@runtime_checkable
class EvalSetStore(Protocol):
    """Stores labeled corpora (plan 051).

    `bump_labels_version` is separate from `save` on purpose: every label
    write bumps the version, and runs pin the version they scored against.
    Folding it into `save` would let a CRUD edit of the *name* invalidate
    every historical score.
    """

    async def get(self, id: str) -> "EvalSet | None": ...
    async def save(self, eval_set: "EvalSetBase | EvalSet") -> None: ...
    async def list(self, limit: int = 50, offset: int = 0) -> "list[EvalSet]": ...
    async def delete(self, id: str) -> bool: ...
    async def bump_labels_version(self, id: str) -> int: ...


@runtime_checkable
class EvalExampleStore(Protocol):
    """Stores one labeled document per row (plan 051).

    `save` upserts on `(eval_set_id, doc_key)`, not on `id`: relabeling a
    document must replace its label, never accumulate a second contradictory
    one that would then be scored twice.
    """

    async def get(self, id: str) -> "EvalExample | None": ...
    async def get_by_doc_key(
        self, eval_set_id: str, doc_key: str
    ) -> "EvalExample | None": ...
    async def save(self, example: "EvalExampleBase | EvalExample") -> None: ...
    async def list_for_set(
        self,
        eval_set_id: str,
        split: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> "list[EvalExample]": ...
    async def count_for_set(self, eval_set_id: str, split: str | None = None) -> int: ...
    async def count_by_label_source(self, eval_set_id: str) -> dict[str, int]: ...
    async def delete(self, id: str) -> bool: ...
