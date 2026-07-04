import os
from dte.store.memory import MemoryPipelineStore, MemoryRunStore

_pipeline_store = MemoryPipelineStore()
_run_store = MemoryRunStore()


def get_pipeline_store():
    return _pipeline_store


def get_run_store():
    return _run_store
