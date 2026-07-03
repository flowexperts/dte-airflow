from abc import ABC, abstractmethod
import ibis


class BaseEngine(ABC):
    @abstractmethod
    def execute_to_json(self, table: ibis.Table, output_path: str) -> int:
        ...
