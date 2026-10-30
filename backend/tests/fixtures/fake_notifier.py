"""A stand-in for a provider notifier (plan 070): records what it was sent."""
from airflow.sdk import BaseNotifier

SENT: list[dict] = []


class FakeNotifier(BaseNotifier):
    template_fields = ("text",)

    def __init__(self, *, target_conn_id: str, text: str = "{{ dte_message }}", **kw):
        super().__init__(**kw)
        self.target_conn_id = target_conn_id
        self.text = text

    def notify(self, context):
        SENT.append({"conn": self.target_conn_id, "text": self.text})
