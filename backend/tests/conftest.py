import pytest
import json
from pathlib import Path


@pytest.fixture
def sample_json_file(tmp_path):
    data = [
        {"name": "alice", "age": 30, "score": 9.5, "active": True},
        {"name": "bob", "age": 25, "score": 8.0, "active": False},
        {"name": "carol", "age": 35, "score": 7.5, "active": True},
    ]
    p = tmp_path / "sample.json"
    p.write_text(json.dumps(data))
    return str(p)
