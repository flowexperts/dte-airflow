from abc import ABC, abstractmethod
import ibis


class BaseEngine(ABC):
    @abstractmethod
    def load_json(self, source_id: str, path: str) -> ibis.Table:
        ...

    @abstractmethod
    def execute_to_json(self, table: ibis.Table, output_path: str) -> int:
        ...
