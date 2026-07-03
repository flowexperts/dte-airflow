from abc import ABC, abstractmethod
import ibis


class BaseConnector(ABC):
    @abstractmethod
    def load(self, source_id: str, **kwargs) -> ibis.Table:
        ...
