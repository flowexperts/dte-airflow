from dte.api import deps
from dte.store.memory import MemoryPipelineStore, MemoryRunStore


def test_memory_stores_selected_when_database_url_unset():
    assert deps._db_url is None or deps._db_url == ""
    assert isinstance(deps.get_pipeline_store(), MemoryPipelineStore)
    assert isinstance(deps.get_run_store(), MemoryRunStore)
