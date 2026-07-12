from abc import ABC, abstractmethod
import ibis


class BaseEngine(ABC):
    @abstractmethod
    def execute(self, table: ibis.Table, target) -> dict:
        ...

    def execute_to_json(self, table: ibis.Table, output_path: str) -> int:
        from dte.models.pipeline import JsonFileTarget
        result = self.execute(table, JsonFileTarget(type="json_file", path=output_path))
        return result["rows_written"]
