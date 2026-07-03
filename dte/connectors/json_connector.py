import ibis
from dte.connectors.base import BaseConnector


class JsonConnector(BaseConnector):
    def __init__(self, con: ibis.BaseBackend):
        self.con = con

    def load(self, source_id: str, path: str, **kwargs) -> ibis.Table:
        return self.con.read_json(path)
