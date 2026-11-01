"""Every react_app name in plugin.py is registered by the UI bundle (plan 067).

Airflow 3.3 finds a react_app's component at `globalThis[name]`; a name the
bundle doesn't register renders Airflow's 404 once the shared bundle is cached.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_bundle_registers_every_plugin_name():
    src = (ROOT / "backend/dte/airflow/plugin.py").read_text()
    # Names are literals in the tuples/dicts of `react_apps`.
    names = {
        n.value for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Tuple) and len(n.elts) == 2
        and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in n.elts)
        for n in [n.elts[0]]
    } | {
        # ...or a literal "name" in a react_apps dict (the run-view tab).
        v.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Dict)
        for k, v in zip(n.keys, n.values)
        if isinstance(k, ast.Constant) and k.value == "name" and isinstance(v, ast.Constant)
        and any(isinstance(k2, ast.Constant) and k2.value == "bundle_url" for k2 in n.keys)
    }
    bundle = (ROOT / "frontend/src/plugin.tsx").read_text()
    block = re.search(r"ENTRY_NAMES = \[(.*?)\]", bundle, re.S).group(1)
    registered = set(re.findall(r'"([^"]+)"', block))
    assert names == registered
